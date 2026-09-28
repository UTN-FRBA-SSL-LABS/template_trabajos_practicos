#!/usr/bin/env python3
"""Publish the test outcome on the tested SHA from a trusted runner."""
import os
from pathlib import Path
from review_state import GitHub

gh = GitHub()
head = os.environ["HEAD_SHA"]
result = os.environ["TEST_RESULT"]
run_url = f"https://github.com/{gh.repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
passed = result == "success"
gh.api("POST", f"statuses/{head}", {"context": "SSL / Tests de entrega", "state": "success" if passed else "failure",
       "description": "Compilación y tests aprobados" if passed else "Tests no aprobados o ejecución interrumpida",
       "target_url": run_url})
body = f"## Tests remotos — `{head}`\n\n" + ("Compilación y tests aprobados." if passed else "La compilación o los tests no terminaron correctamente. No se habilita una nueva evaluación LLM.")
body += f"\n\n[Ver ejecución y logs]({run_url})."
quality = Path(".quality/quality-report.md")
if quality.is_file():
    body += "\n\n<details><summary>Calidad de código (informativo)</summary>\n\n" + quality.read_text(errors="replace")[:30000] + "\n\n</details>"
# An older run must not overwrite the notice for a newer PR head.
pr = gh.api("GET", f"pulls/{os.environ['PR_NUMBER']}")
if pr["head"]["sha"] == head:
    gh.comment(os.environ["PR_NUMBER"], body, "<!-- ssl-test-result -->")
