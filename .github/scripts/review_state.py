"""GitHub API and durable review state. No student code is executed by this module."""
import base64
from datetime import datetime, timezone
import json
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BRANCH = "ssl-evaluaciones"
MARKER = "<!-- ssl-llm-review -->"
BOT = "github-actions[bot]"


class APIError(RuntimeError):
    def __init__(self, status, method, path):
        self.status = status
        super().__init__(f"GitHub API {method} {path}: HTTP {status}")


class GitHub:
    def __init__(self, repo=None, token=None):
        self.repo = repo or os.environ["GITHUB_REPOSITORY"]
        self.token = token or os.environ["GITHUB_TOKEN"]

    def api(self, method, path, data=None, missing=False):
        req = Request(f"https://api.github.com/repos/{self.repo}/{path}",
                      data=json.dumps(data).encode() if data is not None else None,
                      method=method, headers={"Authorization": f"Bearer {self.token}",
                      "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                      "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as e:
            if missing and e.code == 404:
                return None
            raise APIError(e.code, method, path) from None

    def pages(self, path):
        for page in range(1, 101):
            sep = "&" if "?" in path else "?"
            values = self.api("GET", f"{path}{sep}per_page=100&page={page}")
            yield from values
            if len(values) < 100:
                return
        raise RuntimeError("Demasiadas páginas: no se puede verificar el historial completo.")

    def comment(self, pr, body, marker=MARKER):
        marked = body + "\n" + marker
        for comment in self.pages(f"issues/{pr}/comments"):
            if comment["user"]["login"] == BOT and marker in comment.get("body", ""):
                if comment["body"] != marked:
                    self.api("PATCH", f"issues/comments/{comment['id']}", {"body": marked})
                return
        self.api("POST", f"issues/{pr}/comments", {"body": marked})


def validate_branch(branch):
    if branch not in {"TP_1", "TP_2", "TP_3", "TP_4"}:
        raise ValueError("La entrega debe usar TP_1, TP_2, TP_3 o TP_4.")
    return branch.replace("_", "")


def is_codeowner(text, actor):
    # Current repositories have a global user list. Fail closed if policy grows
    # to teams or path rules; never silently treat a collaborator as a CODEOWNER.
    owners = None
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if fields[0] != "*" or len(fields) < 2 or any(not re.fullmatch(r"@[A-Za-z0-9-]+", x) for x in fields[1:]):
            raise ValueError("CODEOWNERS requiere resolver equipos/reglas por ruta antes de autorizar una reevaluación.")
        owners = {x[1:].lower() for x in fields[1:]}
    return bool(owners and actor.lower() in owners)


class Ledger:
    def __init__(self, gh):
        self.gh = gh

    def read(self, branch):
        validate_branch(branch)
        ref = self.gh.api("GET", f"git/ref/heads/{BRANCH}", missing=True)
        if not ref:
            return None
        content = self.gh.api("GET", f"contents/evaluaciones/{branch}.json?ref={ref['object']['sha']}", missing=True)
        if not content:
            return None
        state = json.loads(base64.b64decode(content["content"]))
        if state.get("schema") != 1 or state.get("branch") != branch or not state.get("reports"):
            raise ValueError("Registro de evaluaciones inválido; se requiere intervención docente.")
        for record in state["reports"]:
            if not record.get("report") or not record.get("pr") or not record.get("report_path"):
                raise ValueError("Registro incompleto; no se invocará el LLM.")
        return state

    def save(self, branch, record):
        """One fast-forward commit atomically publishes the report and completion record."""
        validate_branch(branch)
        for _ in range(5):
            ref = self.gh.api("GET", f"git/ref/heads/{BRANCH}", missing=True)
            parent = ref["object"]["sha"] if ref else None
            state = self.read(branch) or {"schema": 1, "branch": branch, "reports": []}
            if any(r["id"] == record["id"] for r in state["reports"]):
                return state
            state["reports"].append(record)
            tree_data = {"tree": [
                {"path": f"evaluaciones/{branch}.json", "mode": "100644", "type": "blob",
                 "content": json.dumps(state, ensure_ascii=False, indent=2) + "\n"},
                {"path": record["report_path"], "mode": "100644", "type": "blob", "content": record["report"]},
            ]}
            if parent:
                tree_data["base_tree"] = self.gh.api("GET", f"git/commits/{parent}")["tree"]["sha"]
            else:
                tree_data["tree"].append({"path": "README.md", "mode": "100644", "type": "blob",
                    "content": "# Evaluaciones SSL\n\nRegistro docente de devoluciones completas, sin vencimiento automático.\nNo borrar esta rama ni sus archivos.\n"})
            tree = self.gh.api("POST", "git/trees", tree_data)
            commit = self.gh.api("POST", "git/commits", {"message": f"Registrar devolución {branch} ({record['id']})",
                               "tree": tree["sha"], "parents": [parent] if parent else []})
            try:
                if parent:
                    self.gh.api("PATCH", f"git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": False})
                else:
                    self.gh.api("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
                return state
            except APIError as error:
                if error.status not in {409, 422}:
                    raise
        raise RuntimeError("No se pudo guardar la devolución por cambios concurrentes en el registro.")


def report_record(branch, pr, head, report, generation, **extra):
    validate_branch(branch)
    if not re.fullmatch(r"[A-Za-z0-9-]+", generation):
        raise ValueError("Identificador de evaluación inválido.")
    return {"id": generation, "pr": int(pr), "head_sha": head, "report": report,
            "report_path": f"reportes/{branch}/{generation}.md",
            "completed_at": datetime.now(timezone.utc).isoformat(), **extra}


def publish_saved(gh, branch, pr, state):
    record = state["reports"][-1]
    origin = f"https://github.com/{gh.repo}/pull/{record['pr']}"
    report_url = f"https://github.com/{gh.repo}/blob/{BRANCH}/{record['report_path']}"
    version = f"`{record['head_sha']}`" if record.get("head_sha") else "la versión de la devolución histórica (su SHA no quedó registrado)"
    policy = (f"## Devolución LLM registrada — {branch}\n\n"
              f"Esta rama ya recibió una devolución completa en el [PR #{record['pr']}]({origin}). "
              f"Los tests determinísticos habían aprobado para {version}. Esa aprobación no se extiende a commits posteriores.\n\n"
              "Hay una devolución automática por repositorio y rama de TP. Nuevos commits, cerrar/reabrir el PR "
              "o crear otro desde la misma rama no habilitan otra llamada. Los tests remotos siguen verificando las nuevas entregas "
              "con constancia local válida. Solo los CODEOWNERS pueden solicitar una reevaluación manual.\n\n"
              f"[Ver devolución completa guardada]({report_url}). El registro no vence automáticamente.\n\n---\n\n")
    # GitHub's comment limit must not cause a second model request.
    body = policy + record["report"]
    if len(body) > 60000:
        body = policy
    gh.comment(pr, body)
