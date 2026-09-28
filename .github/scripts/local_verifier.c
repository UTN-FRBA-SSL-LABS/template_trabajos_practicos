/* Infraestructura docente. Verifica una copia limpia del índice de Git.
 * El alumno usa make verificar y programa únicamente su TP en C/Flex/Bison.
 * Requiere POSIX (Linux, macOS o WSL), cc, Git y la suite existente. */
#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

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
static volatile sig_atomic_t active_child = 0;

static void fail(const char *message) {
  fprintf(stderr, "Verificación fallida: %s\n", message);
  exit(EXIT_FAILURE);
}

static void interrupted(int sig) {
  if (active_child > 0) kill(-(pid_t)active_child, SIGKILL);
  _exit(128 + sig);
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
    unsetenv("MAKEFLAGS");
    unsetenv("MFLAGS");
    unsetenv("MAKEOVERRIDES");
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

static char *capture(char *const argv[], size_t *length) {
  FILE *stream = tmpfile();
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
  for (char *end = p + 1;; ++end) {
    if (*end != '/' && *end != '\0') continue;
    char saved = *end;
    *end = '\0';
    if (mkdir(p, 0700) && errno != EEXIST)
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
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL,
                  !strcmp(entry->mode, "100755") ? 0755 : 0644);
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
  FILE *file = fopen(path, "w");
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

int main(int argc, char **argv) {
  if (argc != 3 || strlen(argv[1]) != 3 || strncmp(argv[1], "TP", 2) ||
      argv[1][2] < '1' || argv[1][2] > '4')
    fail("Uso: make -C TPN verificar.");
  signal(SIGINT, interrupted);
  signal(SIGTERM, interrupted);
  const char *tp = argv[1];
  char *root =
      capture((char *[]){"git", "rev-parse", "--show-toplevel", NULL}, NULL);
  root[strcspn(root, "\r\n")] = '\0';
  if (chdir(root)) fail("No se pudo entrar al repositorio.");
  char *receipt = join(tp, ".verificacion-local.json");
  FILE *failed = fopen(receipt, "w");
  if (!failed) fail("No se pudo invalidar la constancia anterior.");
  if (fprintf(failed, "{\"result\":\"failed\",\"tp\":\"%s\"}\n", tp) < 0 ||
      fclose(failed))
    fail("No se pudo invalidar la constancia anterior.");
  free(receipt);
  check_dirty(tp);
  Snapshot before = snapshot(tp);
  export_files(&before, argv[2]);
  char *work = join(argv[2], tp);
  if (chdir(work)) fail("No se pudo entrar a la copia limpia.");
  double deadline = now() + SSL_TEST_TIMEOUT;
  run((char *[]){"make", NULL}, -1, SSL_TEST_TIMEOUT);
  double remaining = deadline - now();
  if (remaining <= 0) fail("Se agotó el tiempo de verificación.");
  char binary[] = "./bin/tp1";
  binary[8] = tp[2];
  run((char *[]){"sh", "tests/run_testsuite.sh", binary, NULL}, -1, remaining);
  if (chdir(root)) fail("No se pudo volver al repositorio.");
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
