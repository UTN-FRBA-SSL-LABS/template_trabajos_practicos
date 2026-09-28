#!/usr/bin/env python3
"""Informative checks, once per delivery, without an additional runner."""
from pathlib import Path
import subprocess
import sys

tp = sys.argv[1]
files = sorted(str(p) for p in Path(tp).rglob("*") if p.suffix in {".c", ".h", ".cpp", ".hpp"}
               and not p.is_symlink() and not any(x in p.parts for x in {"bin", "obj", ".deps"})
               and not any(x in p.name for x in {"lex.yy", ".tab."}))
commands = [("clang-format", ["clang-format", "--dry-run", "-Werror", *files]),
            ("cppcheck", ["cppcheck", "--enable=all", "--suppress=missingIncludeSystem", tp]),
            ("cpplint", ["cpplint", "--filter=-legal/copyright", *files])]
report = [f"# Calidad de código — {tp}\n\nInformativo: no modifica el resultado de los tests.\n"]
for label, args in commands:
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        text = result.stdout[:8000] or "Sin observaciones."
    except (OSError, subprocess.TimeoutExpired) as error:
        text = f"No se pudo completar este análisis: {type(error).__name__}."
    report.append(f"## {label}\n\n````\n{text}\n````\n")
Path("quality-report.md").write_text("\n".join(report))
