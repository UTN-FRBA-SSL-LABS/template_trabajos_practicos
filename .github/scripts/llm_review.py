#!/usr/bin/env python3
"""
LLM Code Review — SSL UTN-FRBA

Recolecta archivos fuente de un TP y estadísticas de colaboración git,
llama una sola vez a Anthropic, guarda la devolución y publica un comentario.

Uso:
    python llm_review.py

Variables de entorno requeridas:
    ANTHROPIC_API_KEY, GITHUB_TOKEN, PR_NUMBER,
    GITHUB_REPOSITORY, BASE_SHA, HEAD_SHA
"""

import os
import sys
import subprocess
import signal
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
MODEL = "claude-sonnet-4-6"
MAX_TOKENS_OUTPUT = 4096

# Límites de truncado para evitar prompts excesivamente costosos
MAX_FILE_LINES = 500          # líneas máximas por archivo individual
MAX_TOTAL_SOURCE_CHARS = 100_000  # ~25 K tokens de código fuente total

# ---------------------------------------------------------------------------
# Textos que aparecen en el prompt cuando faltan datos
# Centralizados aquí para facilitar su edición sin buscar dentro de funciones
# ---------------------------------------------------------------------------
MSG_NO_SOURCES      = "*(No se encontraron archivos fuente)*"
MSG_NO_QUALITY      = "*(No disponible — el job de calidad no generó reporte o no se ejecutó)*"
MSG_COAUTHORS_TRUNC = "\n*(mensajes truncados)*"
MSG_FILE_TRUNC      = "// ... [archivo truncado: se muestran {lines} de {total} líneas]"
MSG_BUDGET_TRUNC    = "// ... [truncado por límite de presupuesto de tokens]"


# ---------------------------------------------------------------------------
# Recolección de archivos fuente
# ---------------------------------------------------------------------------
def collect_source_files(tp_dir: str) -> dict:
    """Read Git blobs as data, never checkout or execute the student's scripts."""
    from local_receipt import entries, git as git_bytes
    files = {}
    budget = MAX_TOTAL_SOURCE_CHARS
    for path, (_, oid) in sorted(entries(tp_dir, os.environ["HEAD_SHA"]).items()):
        if Path(path).suffix not in {".c", ".h", ".l", ".y"}:
            continue
        if any(p in path for p in ("lex.yy.c", ".tab.c", ".tab.h")):
            continue
        raw = git_bytes("cat-file", "blob", oid).decode(errors="replace")
        lines = raw.splitlines()
        content = "\n".join(lines[:MAX_FILE_LINES])
        if len(lines) > MAX_FILE_LINES:
            content += "\n" + MSG_FILE_TRUNC.format(lines=MAX_FILE_LINES, total=len(lines))
        if len(content) > budget:
            content = content[:budget] + "\n" + MSG_BUDGET_TRUNC
        files[path] = content
        budget -= min(len(content), budget)
        if budget <= 0:
            break
    return files


def load_excluded_authors(config_file: str = ".github/config/docentes.txt") -> set:
    """
    Carga la lista de usernames/nombres a excluir del análisis de colaboración.
    Se compara (case-insensitive) contra nombre y email de cada commit.
    """
    path = Path(config_file)
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def is_excluded(name: str, email: str, excluded: set) -> bool:
    name_l, email_l = name.lower(), email.lower()
    return any(ex in name_l or ex in email_l for ex in excluded)


def collect_readme(tp_dir: str) -> str:
    from local_receipt import blob
    try:
        return blob(os.environ["HEAD_SHA"], tp_dir + "/README.md").decode(errors="replace")[:30000]
    except subprocess.CalledProcessError:
        return "*(README.md no encontrado)*"


def collect_quality_report() -> str:
    """
    Lee el reporte de calidad generado por el job quality (clang-format + cppcheck).
    La ruta viene de la variable de entorno QUALITY_REPORT_PATH.
    Devuelve cadena vacía si no existe o si la variable no está seteada.
    """
    path_str = os.environ.get("QUALITY_REPORT_PATH", "")
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.exists():
        return ""
    return path.read_text(errors="replace")[:20000]


# ---------------------------------------------------------------------------
# Estadísticas git
# ---------------------------------------------------------------------------
def git(args: list) -> str:
    try:
        r = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=30
        )
        return r.stdout.strip() or "*(sin datos)*"
    except Exception as e:
        return f"*(error al ejecutar git: {e})*"


def collect_per_commit_stats(base_sha: str, head_sha: str, excluded: set) -> dict:
    """
    Devuelve un dict sha -> {files, added, removed} para commits de alumnos.
    Usa --numstat por commit para obtener las stats individuales.
    """
    ref = f"{base_sha}..{head_sha}"
    raw = git(["log", ref, "--no-merges", "--numstat",
               "--format=>>>COMMIT:%h|%an|%ae"])

    stats = {}
    current = None
    include = False
    f = a = r = 0

    for line in raw.splitlines():
        if line.startswith(">>>COMMIT:"):
            if current and include:
                stats[current] = {"files": f, "added": a, "removed": r}
            parts = line[len(">>>COMMIT:"):].split("|", 2)
            current = parts[0]
            name  = parts[1] if len(parts) > 1 else ""
            email = parts[2] if len(parts) > 2 else ""
            include = not is_excluded(name, email, excluded)
            f = a = r = 0
        elif include and current and line.strip():
            cols = line.split("\t", 2)
            if len(cols) == 3:
                try:
                    a += int(cols[0]) if cols[0] != "-" else 0
                    r += int(cols[1]) if cols[1] != "-" else 0
                    f += 1
                except ValueError:
                    pass

    if current and include:
        stats[current] = {"files": f, "added": a, "removed": r}

    return stats


def collect_git_stats(base_sha: str, head_sha: str, tp_dir: str,
                      excluded: set) -> dict:
    """
    Recolecta estadísticas git del PR filtrando autores excluidos (docentes).
    Usa formato estructurado para parsear y filtrar antes de enviar al LLM.
    """
    ref = f"{base_sha}..{head_sha}"
    diff_ref = f"{base_sha}...{head_sha}"

    # Obtener todos los commits con datos estructurados para filtrar
    raw_log = git(["log", ref, "--no-merges",
                   "--format=DELIM|%h|%an|%ae|%ai|%s"])

    # Parsear y filtrar por autores excluidos
    student_commits = []
    excluded_count = 0
    for line in raw_log.splitlines():
        if not line.startswith("DELIM|"):
            continue
        parts = line.split("|", 5)
        if len(parts) < 6:
            continue
        _, sha, name, email, date, subject = parts
        if is_excluded(name, email, excluded):
            excluded_count += 1
            continue
        student_commits.append({
            "sha": sha, "name": name, "email": email,
            "date": date[:10], "subject": subject
        })

    # Stats por commit (archivos y líneas)
    per_commit = collect_per_commit_stats(base_sha, head_sha, excluded)

    # Reconstruir shortlog solo con commits de alumnos
    author_counts = {}
    for c in student_commits:
        author_counts[c["name"]] = author_counts.get(c["name"], 0) + 1
    shortlog = "\n".join(
        f"  {count}\t{name}"
        for name, count in sorted(author_counts.items(), key=lambda x: -x[1])
    ) or "*(sin commits de alumnos)*"

    # Log legible para el LLM con stats por commit
    def fmt_commit(c):
        s = per_commit.get(c["sha"], {})
        files = s.get("files", "?")
        added = s.get("added", "?")
        removed = s.get("removed", "?")
        return (f"COMMIT {c['sha']} | {c['name']} | {c['date']} "
                f"| {files} archivos | +{added} / -{removed} | {c['subject']}")

    commit_log = "\n".join(fmt_commit(c) for c in student_commits) \
        or "*(sin commits de alumnos)*"

    # Numstat filtrado: reconstruir por autor
    raw_numstat = git(["log", ref, "--no-merges",
                       "--numstat", "--format=>>>AUTHOR:%an|%ae"])
    filtered_numstat = []
    include = False
    for line in raw_numstat.splitlines():
        if line.startswith(">>>AUTHOR:"):
            parts = line[len(">>>AUTHOR:"):].split("|", 1)
            name = parts[0] if parts else ""
            email = parts[1] if len(parts) > 1 else ""
            include = not is_excluded(name, email, excluded)
            if include:
                filtered_numstat.append(f">>> {name}")
        elif include and line.strip():
            filtered_numstat.append(line)

    # Co-authored-by (solo mensajes de commits de alumnos)
    student_shas = [c["sha"] for c in student_commits]
    coauthors = ""
    if student_shas:
        coauthors = git(["log", "--no-walk"] + student_shas + ["--format=%B"])

    return {
        "total_commits":    str(len(student_commits)),
        "excluded_count":   str(excluded_count),
        "shortlog":         shortlog,
        "commit_log":       commit_log,
        "numstat":          "\n".join(filtered_numstat) or "*(sin datos)*",
        "coauthors":        coauthors,
        "diff_stat":        git(["diff", diff_ref, "--stat", "--", tp_dir]),
    }


# ---------------------------------------------------------------------------
# Construcción del prompt
# ---------------------------------------------------------------------------
PROMPTS_DIR = Path(".github/prompts")


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    try:
        return path.read_text(errors="replace")
    except FileNotFoundError:
        print(f"❌ Archivo de prompt no encontrado: {path}")
        sys.exit(1)


def build_prompt(tp_dir: str, rubric: str, source_files: dict,
                 readme: str, git_stats: dict, quality_report: str = "") -> str:

    system = _load_prompt("system.md").replace("{tp_dir}", tp_dir)
    output_template = (
        _load_prompt("output_template.md")
        .replace("{tp_dir}", tp_dir)
        .replace("{MODEL}", MODEL)
    )

    # Sección de archivos fuente
    sources_md = ""
    for path, content in source_files.items():
        ext = Path(path).suffix
        lang = "c" if ext in {".c", ".h"} else "text"
        sources_md += f"\n#### `{path}`\n```{lang}\n{content}\n```\n"
    if not sources_md:
        sources_md = MSG_NO_SOURCES

    # Limitar co-authored raw a 3000 chars para no desperdiciar tokens
    coauthors_trimmed = git_stats["coauthors"][:3000]
    if len(git_stats["coauthors"]) > 3000:
        coauthors_trimmed += MSG_COAUTHORS_TRUNC

    quality_section = quality_report if quality_report else MSG_NO_QUALITY

    data_section = (
        _load_prompt("data_template.md")
        .replace("{rubric}",          rubric)
        .replace("{readme}",          readme)
        .replace("{sources}",         sources_md)
        .replace("{total_commits}",   git_stats["total_commits"])
        .replace("{excluded_count}",  git_stats["excluded_count"])
        .replace("{shortlog}",        git_stats["shortlog"])
        .replace("{commit_log}",      git_stats["commit_log"])
        .replace("{numstat}",         git_stats["numstat"])
        .replace("{tp_dir}",          tp_dir)
        .replace("{diff_stat}",       git_stats["diff_stat"])
        .replace("{coauthors}",       coauthors_trimmed)
        .replace("{quality_report}",  quality_section)
    )

    return f"{system}\n\n---\n\n{data_section}\n\n---\n\n{output_template}"


def generate_report(prompt, client=None):
    """One request, no SDK retries, hard wall-clock deadline including response parsing."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                                     timeout=180.0, max_retries=0)
    def expired(signum, frame):
        raise TimeoutError("La revisión superó los 180 segundos.")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(180)
    try:
        response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS_OUTPUT,
                                          messages=[{"role": "user", "content": prompt}])
        if response.stop_reason != "end_turn":
            raise ValueError(f"Respuesta incompleta ({response.stop_reason}); no consume la devolución.")
        text = "\n".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise ValueError("Respuesta vacía; no consume la devolución.")
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return text, usage
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def review_once(ledger, branch, pr, head, generation, force, generate, publish):
    from review_state import report_record
    state = ledger.read(branch)
    if state and (not force or any(r["id"] == generation for r in state["reports"])):
        publish(state)
        return "reused"
    report, usage = generate()
    record = report_record(branch, pr, head, report, generation, usage=usage, model=MODEL, manual=force)
    state = ledger.save(branch, record)
    # Save first. A comment/API error must never cause another paid call on retry.
    publish(state)
    return "generated"


def main():
    from local_receipt import blob, validate
    from review_state import GitHub, Ledger, is_codeowner, publish_saved, validate_branch
    from submission_gate import fetch_shas
    gh = GitHub()
    pr_number = int(os.environ["PR_NUMBER"])
    pr = gh.api("GET", f"pulls/{pr_number}")
    branch = pr["head"]["ref"]
    tp = validate_branch(branch)
    head, base = os.environ["HEAD_SHA"], pr["base"]["sha"]
    if pr["state"] != "open" or pr["base"]["ref"] != "main":
        raise ValueError("La entrega ya no es un PR abierto a main.")
    if (pr["head"].get("repo") or {}).get("full_name", "").lower() != gh.repo.lower():
        raise ValueError("La rama debe pertenecer al mismo repositorio.")
    if pr["head"]["sha"] != head:
        print("Hay un commit nuevo; no se evalúa una versión reemplazada antes de iniciar la llamada.")
        return
    fetch_shas(base, head)
    manual = os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    force = os.environ.get("FORCE_REVIEW") == "true"
    if manual or force:
        if not manual or os.environ["GITHUB_REF"] != "refs/heads/main":
            raise ValueError("Reevaluación solo mediante workflow_dispatch desde main.")
        if not is_codeowner(blob(base, ".github/CODEOWNERS").decode(), os.environ["GITHUB_TRIGGERING_ACTOR"]):
            raise ValueError("El usuario que inició esta ejecución no es CODEOWNER.")
    validate(tp, head, base)
    os.environ["BASE_SHA"] = base
    rubric = Path(f".github/rubrics/{tp.lower()}_rubric.md").read_text()
    def generate():
        prompt = build_prompt(tp, rubric, collect_source_files(tp), collect_readme(tp),
                              collect_git_stats(base, head, tp, load_excluded_authors()), collect_quality_report())
        return generate_report(prompt)
    result = review_once(Ledger(gh), branch, pr_number, head, os.environ["GITHUB_RUN_ID"], force,
                         generate, lambda state: publish_saved(gh, branch, pr_number, state))
    print(f"Revisión: {result}. Registro y reporte en ssl-evaluaciones.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Exception bodies from providers can contain submitted data; keep logs concise.
        print(f"El job no finalizó: {type(error).__name__}. Una devolución ya guardada no se vuelve a generar al reintentar.")
        raise SystemExit(1)
