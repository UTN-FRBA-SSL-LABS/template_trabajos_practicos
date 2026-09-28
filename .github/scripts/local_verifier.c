/* Infraestructura docente. Verifica una copia limpia del índice de Git.
 * El alumno usa make verificar y programa únicamente su TP en C/Flex/Bison.
 * Usa el entorno GNU del TP: Linux/macOS o Windows con MSYS2/MinGW/Cygwin. */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#if defined(_WIN32) && !defined(__CYGWIN__) && !defined(__MSYS__)
#define SSL_WINDOWS 1
#define WIN32_LEAN_AND_MEAN
#include <direct.h>
#include <io.h>
#include <wchar.h>
#include <windows.h>
#define strdup _strdup
#define strcasecmp _stricmp
#define strtok_r strtok_s
#define fileno _fileno
#define close _close
#else
#include <strings.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#endif

#ifndef SSL_TEST_TIMEOUT
#define SSL_TEST_TIMEOUT 120
#endif

typedef struct {
  char *path;
  char mode[7];
  char oid[65];
} Entry;
typedef struct {
  Entry *files;
  size_t count;
  char *recipe[2];
} Snapshot;
static const char *recipes[] = {".github/scripts/local_verifier.c",
                                ".github/scripts/verificar_local.sh"};
#ifdef SSL_WINDOWS
static HANDLE active_job = NULL;
#else
static volatile sig_atomic_t active_child = 0;
#endif

static void fail(const char *message) {
  fprintf(stderr, "Verificación fallida: %s\n", message);
  exit(EXIT_FAILURE);
}

static void interrupted(int sig) {
#ifdef SSL_WINDOWS
  if (active_job) TerminateJobObject(active_job, 128 + sig);
  ExitProcess(128 + sig);
#else
  if (active_child > 0) kill(-(pid_t)active_child, SIGKILL);
  _exit(128 + sig);
#endif
}

static void *allocate(size_t size) {
  void *p = malloc(size ? size : 1);
  if (!p) fail("Sin memoria.");
  return p;
}

static char *copy(const char *s) {
  char *p = strdup(s);
  if (!p) fail("Sin memoria.");
  return p;
}

static char *join(const char *a, const char *b) {
  size_t size = strlen(a) + strlen(b) + 2;
  char *p = allocate(size);
  snprintf(p, size, "%s/%s", a, b);
  return p;
}

#ifdef SSL_WINDOWS
static wchar_t *wide(const char *s) {
  int length =
      MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0);
  if (!length) fail("Ruta o argumento UTF-8 inválido.");
  wchar_t *result = allocate((size_t)length * sizeof(*result));
  if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, result,
                           length))
    fail("No se pudo convertir la ruta o argumento.");
  return result;
}

static char *utf8(const wchar_t *s) {
  int length = WideCharToMultiByte(CP_UTF8, 0, s, -1, NULL, 0, NULL, NULL);
  if (!length) fail("No se pudo convertir el argumento.");
  char *result = allocate((size_t)length);
  if (!WideCharToMultiByte(CP_UTF8, 0, s, -1, result, length, NULL, NULL))
    fail("No se pudo convertir el argumento.");
  return result;
}

static int change_directory(const char *path) {
  wchar_t *name = wide(path);
  int result = _wchdir(name);
  free(name);
  return result;
}

static FILE *open_file(const char *path, const char *mode) {
  wchar_t *name = wide(path), *flags = wide(mode);
  FILE *result = _wfopen(name, flags);
  free(name);
  free(flags);
  return result;
}

static int make_directory(const char *path) {
  wchar_t *name = wide(path);
  int result = _wmkdir(name);
  free(name);
  return result;
}

static int create_file(const char *path, int executable) {
  (void)executable;
  wchar_t *name = wide(path);
  int result = _wopen(name, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                      _S_IREAD | _S_IWRITE);
  free(name);
  return result;
}

/* MS C runtime quoting: quotes, spaces and trailing backslashes remain literal.
 * No cmd.exe or shell interpolation is used to launch native child processes.
 */
static wchar_t *command_line(char *const argv[]) {
  size_t capacity = 1;
  for (size_t i = 0; argv[i]; ++i) capacity += 2 * strlen(argv[i]) + 4;
  wchar_t *result = allocate(capacity * sizeof(*result)), *out = result;
  for (size_t i = 0; argv[i]; ++i) {
    wchar_t *arg = wide(argv[i]);
    if (i) *out++ = L' ';
    *out++ = L'"';
    const wchar_t *p = arg;
    while (*p) {
      size_t slashes = 0;
      while (*p == L'\\') {
        ++slashes;
        ++p;
      }
      size_t escaped = (*p == L'"' || !*p) ? slashes * 2 : slashes;
      while (escaped--) *out++ = L'\\';
      if (*p == L'"') *out++ = L'\\';
      if (*p) *out++ = *p++;
    }
    *out++ = L'"';
    free(arg);
  }
  *out = L'\0';
  return result;
}

static HANDLE inherited_handle(HANDLE source, int input) {
  HANDLE result;
  if (!source || source == INVALID_HANDLE_VALUE) {
    SECURITY_ATTRIBUTES security = {sizeof(security), NULL, TRUE};
    result = CreateFileW(L"NUL", input ? GENERIC_READ : GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, &security,
                         OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (result == INVALID_HANDLE_VALUE)
      fail("No se pudo abrir la salida del comando.");
  } else if (!DuplicateHandle(GetCurrentProcess(), source, GetCurrentProcess(),
                              &result, 0, TRUE, DUPLICATE_SAME_ACCESS)) {
    fail("No se pudo preparar la salida del comando.");
  }
  return result;
}

static double now(void) { return (double)GetTickCount64() / 1000.0; }

static void run(char *const argv[], int output, double seconds) {
  HANDLE job = CreateJobObjectW(NULL, NULL);
  if (!job) fail("No se pudo crear el grupo de procesos.");
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits = {0};
  limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits,
                               sizeof(limits))) {
    CloseHandle(job);
    fail("No se pudo configurar el timeout de procesos.");
  }
  active_job = job;
  STARTUPINFOW startup = {0};
  startup.cb = sizeof(startup);
  startup.dwFlags = STARTF_USESTDHANDLES;
  startup.hStdInput = inherited_handle(GetStdHandle(STD_INPUT_HANDLE), 1);
  startup.hStdOutput =
      inherited_handle(output >= 0 ? (HANDLE)_get_osfhandle(output)
                                   : GetStdHandle(STD_OUTPUT_HANDLE),
                       0);
  startup.hStdError = inherited_handle(GetStdHandle(STD_ERROR_HANDLE), 0);
  PROCESS_INFORMATION process = {0};
  wchar_t *line = command_line(argv);
  BOOL created = CreateProcessW(NULL, line, NULL, NULL, TRUE, CREATE_SUSPENDED,
                                NULL, NULL, &startup, &process);
  free(line);
  CloseHandle(startup.hStdInput);
  CloseHandle(startup.hStdOutput);
  CloseHandle(startup.hStdError);
  if (!created) {
    CloseHandle(job);
    active_job = NULL;
    fail(
        "No se pudo iniciar el comando. Revisar las herramientas GNU en PATH.");
  }
  if (!AssignProcessToJobObject(job, process.hProcess) ||
      ResumeThread(process.hThread) == (DWORD)-1) {
    TerminateProcess(process.hProcess, 1);
    WaitForSingleObject(process.hProcess, INFINITE);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    CloseHandle(job);
    active_job = NULL;
    fail("No se pudo supervisar el grupo de procesos.");
  }
  CloseHandle(process.hThread);
  DWORD waited = WaitForSingleObject(process.hProcess,
                                     seconds > 0 ? (DWORD)(seconds * 1000) : 0);
  DWORD code = 1;
  BOOL obtained = GetExitCodeProcess(process.hProcess, &code);
  /* Closing the job kills descendants too, even when make/sh have already
   * exited. */
  CloseHandle(job);
  active_job = NULL;
  WaitForSingleObject(process.hProcess, INFINITE);
  CloseHandle(process.hProcess);
  if (waited == WAIT_TIMEOUT)
    fail("Se agotó el tiempo de verificación; constancia invalidada.");
  if (waited != WAIT_OBJECT_0 || !obtained || code)
    fail("El comando no aprobó; constancia invalidada.");
}
#else
static int change_directory(const char *path) { return chdir(path); }
static FILE *open_file(const char *path, const char *mode) {
  return fopen(path, mode);
}
static int make_directory(const char *path) { return mkdir(path, 0700); }
static int create_file(const char *path, int executable) {
  return open(path, O_WRONLY | O_CREAT | O_EXCL, executable ? 0755 : 0644);
}

static double now(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts)) fail("No se pudo leer el reloj.");
  return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void run(char *const argv[], int output, double seconds) {
  double deadline = now() + seconds;
  pid_t pid = fork();
  if (pid < 0) fail("No se pudo iniciar el comando.");
  if (!pid) {
    if (setpgid(0, 0)) _exit(125);
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
    if (output >= 0 && dup2(output, STDOUT_FILENO) < 0) _exit(125);
    execvp(argv[0], argv);
    perror(argv[0]);
    _exit(127);
  }
  active_child = pid;
  (void)setpgid(pid, pid);
  int status = 0;
  for (;;) {
    pid_t result = waitpid(pid, &status, WNOHANG);
    if (result == pid) break;
    if (result < 0 && errno != EINTR) fail("No se pudo esperar el comando.");
    if (now() >= deadline) {
      kill(-pid, SIGKILL);
      while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
      }
      active_child = 0;
      fail("Se agotó el tiempo de verificación; constancia invalidada.");
    }
    struct timespec pause = {0, 10000000};
    nanosleep(&pause, NULL);
  }
  active_child = 0;
  if (!WIFEXITED(status) || WEXITSTATUS(status))
    fail("El comando no aprobó; constancia invalidada.");
}
#endif

static char *capture(char *const argv[], size_t *length) {
#ifdef SSL_WINDOWS
  wchar_t folder[MAX_PATH + 1], name[MAX_PATH + 1];
  DWORD count = GetTempPathW(MAX_PATH + 1, folder);
  if (!count || count > MAX_PATH || !GetTempFileNameW(folder, L"ssl", 0, name))
    fail("No se pudo crear un archivo temporal.");
  HANDLE handle =
      CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
                  FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, NULL);
  if (handle == INVALID_HANDLE_VALUE) {
    DeleteFileW(name);
    fail("No se pudo abrir el archivo temporal.");
  }
  int fd = _open_osfhandle((intptr_t)handle, _O_RDWR | _O_BINARY);
  if (fd < 0) {
    CloseHandle(handle);
    fail("No se pudo capturar la respuesta.");
  }
  FILE *stream = _fdopen(fd, "w+b");
#else
  FILE *stream = tmpfile();
#endif
  if (!stream) fail("No se pudo crear un archivo temporal.");
  run(argv, fileno(stream), 30);
  if (fseek(stream, 0, SEEK_END)) fail("No se pudo leer la respuesta.");
  long size = ftell(stream);
  if (size < 0 || fseek(stream, 0, SEEK_SET))
    fail("No se pudo leer la respuesta.");
  char *data = allocate((size_t)size + 1);
  if (fread(data, 1, (size_t)size, stream) != (size_t)size)
    fail("Respuesta incompleta.");
  data[size] = '\0';
  fclose(stream);
  if (length) *length = (size_t)size;
  return data;
}

static int suffix(const char *s, const char *ending) {
  size_t a = strlen(s), b = strlen(ending);
  return a >= b && !strcasecmp(s + a - b, ending);
}

static int relevant(const char *path, const char *tp) {
  if (strncmp(path, tp, 3) || path[3] != '/') return 0;
  char *parts = copy(path + 4), *save = NULL;
  const char *name = strrchr(path, '/') + 1;
  int count = 0;
  for (char *part = strtok_r(parts, "/", &save); part;
       part = strtok_r(NULL, "/", &save)) {
    count++;
    if (!strcmp(part, "bin") || !strcmp(part, "obj") ||
        !strcmp(part, ".deps") || !strcmp(part, ".vscode") ||
        !strcmp(part, "__pycache__")) {
      free(parts);
      return 0;
    }
  }
  free(parts);
  if (!strcmp(name, ".verificacion-local.json") || suffix(name, ".md") ||
      suffix(name, ".code-workspace"))
    return 0;
  if (!strncmp(path + 4, "tests/output/", 13))
    return count == 4 && !strncmp(path + 4, "tests/output/expected/", 22) &&
           !(strlen(name) >= 10 &&
             !strcmp(name + strlen(name) - 10, "_clean.txt"));
  return 1;
}

static int valid_oid(const char *s) {
  size_t len = strlen(s);
  if (len != 40 && len != 64) return 0;
  for (size_t i = 0; i < len; ++i)
    if (!isxdigit((unsigned char)s[i])) return 0;
  return 1;
}

static Snapshot snapshot(const char *tp) {
  Snapshot result = {0};
  size_t length;
  char *raw = capture(
      (char *[]){"git", "ls-files", "--stage", "-z", "--", (char *)tp, NULL},
      &length);
  int suite = 0;
  for (char *p = raw; p < raw + length; p += strlen(p) + 1) {
    char *tab = strchr(p, '\t');
    if (!tab) fail("Entrada inválida en Git.");
    const char *path = tab + 1;
    if (!relevant(path, tp)) continue;
    Entry entry = {0};
    int stage = -1;
    if (sscanf(p, "%6s %64s %d", entry.mode, entry.oid, &stage) != 3 ||
        !valid_oid(entry.oid))
      fail("Entrada inválida en Git.");
    if (stage != 0) fail("Resolver conflictos de Git antes de verificar.");
    if (strcmp(entry.mode, "100644") && strcmp(entry.mode, "100755"))
      fail("No se admiten enlaces simbólicos ni submódulos.");
    entry.path = copy(path);
    Entry *files = realloc(result.files, (result.count + 1) * sizeof(*files));
    if (!files) fail("Sin memoria.");
    result.files = files;
    result.files[result.count++] = entry;
    if (!strcmp(path + 4, "tests/run_testsuite.sh")) suite = 1;
  }
  free(raw);
  if (!suite) fail("Falta la suite oficial del TP.");
  for (size_t i = 0; i < 2; ++i) {
    char ref[128];
    snprintf(ref, sizeof(ref), ":%s", recipes[i]);
    result.recipe[i] =
        capture((char *[]){"git", "rev-parse", "--verify", ref, NULL}, NULL);
    result.recipe[i][strcspn(result.recipe[i], "\r\n")] = '\0';
    if (!valid_oid(result.recipe[i]))
      fail("Falta el verificador oficial en Git.");
  }
  return result;
}

static void check_dirty(const char *tp) {
  for (int pass = 0; pass < 2; ++pass) {
    size_t length;
    char *dirty =
        pass == 0
            ? capture((char *[]){"git", "diff", "--name-only", "-z", NULL},
                      &length)
            : capture((char *[]){"git", "ls-files", "--others",
                                 "--exclude-standard", "-z", "--", (char *)tp,
                                 NULL},
                      &length);
    for (char *p = dirty; p < dirty + length; p += strlen(p) + 1)
      if (relevant(p, tp) || !strcmp(p, recipes[0]) || !strcmp(p, recipes[1]))
        fail("Preparar los cambios con git add antes de verificar.");
    free(dirty);
  }
}

static int same(const Snapshot *a, const Snapshot *b) {
  if (a->count != b->count) return 0;
  for (size_t i = 0; i < a->count; ++i)
    if (strcmp(a->files[i].path, b->files[i].path) ||
        strcmp(a->files[i].mode, b->files[i].mode) ||
        strcmp(a->files[i].oid, b->files[i].oid))
      return 0;
  return !strcmp(a->recipe[0], b->recipe[0]) &&
         !strcmp(a->recipe[1], b->recipe[1]);
}

static void mkdirs(const char *path) {
  char *p = copy(path);
  char *start = p + 1;
#ifdef SSL_WINDOWS
  if (strlen(p) > 2 && p[1] == ':') start = p + 3;
  /* An existing UNC server/share is a root, not a directory to create. */
  if (p[0] == '/' && p[1] == '/') {
    char *server = strchr(p + 2, '/');
    char *share = server ? strchr(server + 1, '/') : NULL;
    if (!share) fail("Ruta UNC incompleta.");
    start = share + 1;
  }
#endif
  for (char *end = start;; ++end) {
    if (*end != '/' && *end != '\0') continue;
    char saved = *end;
    *end = '\0';
    if (make_directory(p) && errno != EEXIST)
      fail("No se pudo crear la copia limpia.");
    *end = saved;
    if (!saved) break;
  }
  free(p);
}

static void export_files(const Snapshot *snapshot, const char *directory) {
  for (size_t i = 0; i < snapshot->count; ++i) {
    const Entry *entry = &snapshot->files[i];
    char *path = join(directory, entry->path), *slash = strrchr(path, '/');
    *slash = '\0';
    mkdirs(path);
    *slash = '/';
    int fd = create_file(path, !strcmp(entry->mode, "100755"));
    if (fd < 0) fail("No se pudo exportar un archivo.");
    run((char *[]){"git", "cat-file", "blob", (char *)entry->oid, NULL}, fd,
        30);
    if (close(fd)) fail("No se pudo completar la copia limpia.");
    free(path);
  }
}

static void json_string(FILE *file, const char *s) {
  fputc('"', file);
  for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
    if (*p == '"' || *p == '\\') {
      fputc('\\', file);
      fputc(*p, file);
    } else if (*p < 32)
      fprintf(file, "\\u%04x", *p);
    else
      fputc(*p, file);
  }
  fputc('"', file);
}

static void write_receipt(const char *tp, const Snapshot *snapshot) {
  char *path = join(tp, ".verificacion-local.json");
  FILE *file = open_file(path, "wb");
  if (!file) fail("No se pudo guardar la constancia.");
  fputs("{\"result\":\"passed\",\"inputs\":{\"schema\":2,\"tp\":", file);
  json_string(file, tp);
  fputs(",\"files\":{", file);
  for (size_t i = 0; i < snapshot->count; ++i) {
    const Entry *entry = &snapshot->files[i];
    if (i) fputc(',', file);
    json_string(file, entry->path);
    fprintf(file, ":{\"mode\":\"%s\",\"oid\":\"%s\"}", entry->mode, entry->oid);
  }
  fputs("},\"recipe_oids\":{", file);
  for (size_t i = 0; i < 2; ++i) {
    if (i) fputc(',', file);
    json_string(file, recipes[i]);
    fputc(':', file);
    json_string(file, snapshot->recipe[i]);
  }
  fputs("}}}\n", file);
  int failed = ferror(file);
  if (fclose(file) || failed) fail("No se pudo completar la constancia.");
  free(path);
}

static int verify(int argc, char **argv) {
  if ((argc != 3 && argc != 7) || strlen(argv[1]) != 3 ||
      strncmp(argv[1], "TP", 2) || argv[1][2] < '1' || argv[1][2] > '4')
    fail("Uso: make -C TPN verificar.");
  signal(SIGINT, interrupted);
  signal(SIGTERM, interrupted);
#ifdef SSL_WINDOWS
  _putenv_s("MAKEFLAGS", "");
  _putenv_s("MFLAGS", "");
  _putenv_s("MAKEOVERRIDES", "");
#else
  unsetenv("MAKEFLAGS");
  unsetenv("MFLAGS");
  unsetenv("MAKEOVERRIDES");
#endif
  const char *tp = argv[1];
  char *root =
      argc == 7
          ? copy(argv[3])
          : capture((char *[]){"git", "rev-parse", "--show-toplevel", NULL},
                    NULL);
  root[strcspn(root, "\r\n")] = '\0';
  if (change_directory(root)) fail("No se pudo entrar al repositorio.");
  char *receipt = join(tp, ".verificacion-local.json");
  FILE *failed = open_file(receipt, "wb");
  if (!failed) fail("No se pudo invalidar la constancia anterior.");
  if (fprintf(failed, "{\"result\":\"failed\",\"tp\":\"%s\"}\n", tp) < 0 ||
      fclose(failed))
    fail("No se pudo invalidar la constancia anterior.");
  free(receipt);
  check_dirty(tp);
  Snapshot before = snapshot(tp);
  export_files(&before, argv[2]);
  char *work = join(argv[2], tp);
  if (change_directory(work)) fail("No se pudo entrar a la copia limpia.");
  double deadline = now() + SSL_TEST_TIMEOUT;
  char *make_program = argc == 7 ? argv[4] : "make";
  const char *compiler = argc == 7 ? argv[5] : "gcc";
  char *cc_option = allocate(strlen(compiler) + 4);
  sprintf(cc_option, "CC=%s", compiler);
  run((char *[]){make_program, cc_option, NULL}, -1, SSL_TEST_TIMEOUT);
  double remaining = deadline - now();
  if (remaining <= 0) fail("Se agotó el tiempo de verificación.");
  const char *extension = argc == 7 ? argv[6] : "";
  char *binary = allocate(strlen(extension) + 10);
  sprintf(binary, "./bin/tp%c%s", tp[2], extension);
  run((char *[]){"sh", "tests/run_testsuite.sh", binary, NULL}, -1, remaining);
  if (change_directory(root)) fail("No se pudo volver al repositorio.");
  Snapshot after = snapshot(tp);
  if (!same(&before, &after))
    fail("El índice cambió durante los tests. Volver a verificar.");
  check_dirty(tp);
  write_receipt(tp, &before);
  printf(
      "Tests aprobados. Agregar %s/.verificacion-local.json al commit antes "
      "del push.\n",
      tp);
  return EXIT_SUCCESS;
}

#ifdef SSL_WINDOWS
int wmain(int argc, wchar_t **args) {
  char **argv = allocate(((size_t)argc + 1) * sizeof(*argv));
  for (int i = 0; i < argc; ++i) argv[i] = utf8(args[i]);
  argv[argc] = NULL;
  return verify(argc, argv);
}
#else
int main(int argc, char **argv) { return verify(argc, argv); }
#endif
