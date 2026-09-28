#!/usr/bin/env python3
"""Trusted, inexpensive gate: branch, protected paths, local receipt and review history."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess

from local_receipt import blob, git, validate
from review_state import GitHub, Ledger, is_codeowner, is_new_submission, publish_saved, validate_branch


def fetch_shas(*shas):
    if any(not re.fullmatch(r"[a-f0-9]{40}", sha) for sha in shas):
        raise ValueError("SHA inválido.")
    env = dict(os.environ)
    auth = base64.b64encode(("x-access-token:" + os.environ["GITHUB_TOKEN"]).encode()).decode()
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + auth)
    subprocess.run(["git", "fetch", "--no-tags", "origin", *shas], env=env,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)


def output(values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in values.items():
            stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def test_status(gh, head, state):
    descriptions = {"pending": "Esperando verificación de esta entrega", "failure": "La verificación previa no fue aprobada",
                    "success": "PR previo a la activación: exento del circuito nuevo"}
    gh.api("POST", f"statuses/{head}", {"context": "SSL / Tests de entrega", "state": state,
           "description": descriptions[state],
           "target_url": f"https://github.com/{gh.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"})


def protected(path):
    return (path.startswith((".github/", ".agents/", ".codex/")) or
            path in {".clang-format", "verificar_tp.py"} or
            any(path.startswith(f"TP{n}/tests/") for n in range(1, 5)))


def validate_paths(branch, base, head):
    tp = validate_branch(branch)
    paths = git("diff", "--name-only", "-z", f"{base}...{head}").decode().split("\0")
    paths = [p for p in paths if p]
    if not paths or not any(p.startswith(tp + "/") for p in paths):
        raise ValueError(f"La entrega debe modificar {tp}/.")
    bad = [p for p in paths if protected(p) or not (p.startswith(tp + "/") or p == "README.md")]
    if bad:
        raise ValueError("Cambios fuera del TP o en archivos protegidos: " + ", ".join(bad))


def main():
    gh = GitHub()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    manual = os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
    if manual and os.environ["GITHUB_REF"] != "refs/heads/main":
        raise ValueError("La reevaluación docente debe iniciarse desde main.")
    pr_number = int(os.environ.get("REQUEST_PR", "0")) if manual else event["number"]
    if pr_number <= 0:
        raise ValueError("Número de PR inválido.")
    pr = gh.api("GET", f"pulls/{pr_number}")
    if pr["base"]["ref"] != "main" or pr["state"] != "open":
        raise ValueError("El PR debe estar abierto y dirigido a main.")
    if (pr["head"].get("repo") or {}).get("full_name", "").lower() != gh.repo.lower():
        raise ValueError("La entrega debe provenir de una rama del mismo repositorio.")
    if not manual and pr["head"]["sha"] != event["pull_request"]["head"]["sha"]:
        output({"eligible": False})
        print("Hay un commit más reciente; este evento no inicia tests ni LLM.")
        return
    branch = pr["head"]["ref"]
    tp = validate_branch(branch)
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    fetch_shas(base, head)
    if manual and not is_codeowner(blob(base, ".github/CODEOWNERS").decode(), os.environ["GITHUB_TRIGGERING_ACTOR"]):
        raise ValueError("Solo un CODEOWNER puede solicitar una reevaluación manual.")
    if not is_new_submission(pr["created_at"], os.environ.get("SSL_POLICY_START", "")):
        output({"eligible": False})
        test_status(gh, head, "success")
        print("PR anterior a la activación: no se ejecuta el circuito nuevo ni se modifica su devolución.")
        return
    os.environ["SSL_STATUS_HEAD"] = head
    test_status(gh, head, "pending")
    # Read/report the durable result even if the new local receipt is invalid.
    ledger = Ledger(gh)
    state = ledger.read(branch)
    if state:
        publish_saved(gh, branch, pr_number, state)
    try:
        validate_paths(branch, base, head)
        validate(tp, head, base)
    except (ValueError, subprocess.SubprocessError, OSError) as error:
        gh.comment(pr_number,
            f"## Verificación previa — {tp}\n\nNo se inician compilación, tests remotos ni LLM.\n\n{error}\n\n"
            f"Preparar los cambios con `git add {tp}`, ejecutar `python3 verificar_tp.py {tp}` y agregar "
            f"`{tp}/.verificacion-local.json` al commit. Si cambió main, incorporarlo antes de verificar.",
            "<!-- ssl-submission-gate -->")
        raise
    gh.comment(pr_number, f"## Verificación previa — {tp}\n\nConstancia local válida para `{head}`. "
               "Se habilitan los tests remotos. La constancia verifica coincidencia de contenidos; "
               "el resultado remoto se informa en Actions.", "<!-- ssl-submission-gate -->")
    force = manual and os.environ.get("FORCE_REVIEW") == "true"
    output({"eligible": True, "tp": tp, "branch": branch, "pr": pr_number, "head": head,
            "base": base, "force": force, "needs_llm": not state or force})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if os.environ.get("SSL_STATUS_HEAD"):
            test_status(GitHub(), os.environ["SSL_STATUS_HEAD"], "failure")
        raise SystemExit(f"Verificación previa fallida: {error}")
