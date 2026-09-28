#!/usr/bin/env python3
"""Infraestructura de CI: validar la constancia nativa y ejecutar la suite oficial."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import signal
import tempfile

VERSION = 2
RECIPES = (".github/scripts/local_verifier.c", ".github/scripts/verificar_local.sh")
RECEIPT = ".verificacion-local.json"


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def relevant(path, tp):
    p = PurePosixPath(path)
    if not path.startswith(tp + "/"):
        return False
    rel = p.parts[1:]
    if any(x in {"bin", "obj", ".deps", ".vscode", "__pycache__"} for x in rel):
        return False
    if p.name == RECEIPT or p.suffix.lower() in {".md", ".code-workspace"}:
        return False
    if rel[:2] == ("tests", "output"):
        return len(rel) == 4 and rel[2] == "expected" and not p.name.endswith("_clean.txt")
    return True


def entries(tp, ref=None):
    result = {}
    if ref:
        raw = git("ls-tree", "-rz", ref, "--", tp)
    else:
        raw = git("ls-files", "--stage", "-z", "--", tp)
    for item in raw.split(b"\0"):
        if not item:
            continue
        meta, name = item.split(b"\t", 1)
        path = name.decode("utf-8")
        if not relevant(path, tp):
            continue
        parts = meta.decode().split()
        mode, oid = (parts[0], parts[2]) if ref else (parts[0], parts[1])
        if not ref and parts[2] != "0":
            raise ValueError("Resolver conflictos de Git antes de verificar.")
        if mode not in {"100644", "100755"}:
            raise ValueError(f"No se admiten enlaces simbólicos ni submódulos: {path}")
        result[path] = (mode, oid)
    if not result or f"{tp}/tests/run_testsuite.sh" not in result:
        raise ValueError("Falta la suite oficial del TP.")
    return result


def blob(ref, path):
    return git("show", f"{ref or ''}:{path}")


def fingerprint(tp, ref=None):
    files = {p: {"mode": mode, "oid": oid}
             for p, (mode, oid) in entries(tp, ref).items()}
    return {"schema": VERSION, "tp": tp, "files": files,
            "recipe_oids": {path: git("rev-parse", "--verify", f"{ref or ''}:{path}").decode().strip()
                            for path in RECIPES}}


def validate(tp, head, base):
    expected = fingerprint(tp, head)
    official = fingerprint(tp, base)
    actual = json.loads(blob(head, f"{tp}/{RECEIPT}"))
    if actual.get("result") != "passed" or actual.get("inputs") != expected:
        raise ValueError(f"Constancia ausente o desactualizada. Ejecutar make -C {tp} verificar.")
    if expected["recipe_oids"] != official["recipe_oids"]:
        raise ValueError("Actualizar la rama con main: cambió el verificador oficial.")
    tests = lambda fp: {k: v for k, v in fp["files"].items() if k.startswith(tp + "/tests/")}
    if tests(expected) != tests(official):
        raise ValueError("La suite no coincide con main. Incorporar los tests oficiales y volver a verificar.")


def run_suite(directory, tp, timeout=120):
    """Same commands and acceptance thresholds locally and in CI, always from a clean export."""
    import time
    started = time.monotonic()
    cwd = Path(directory) / tp
    run_bounded(["make"], cwd, timeout)
    remaining = max(1, timeout - (time.monotonic() - started))
    run_bounded(["sh", "tests/run_testsuite.sh", f"./bin/{tp.lower()}"], cwd, remaining)


def run_bounded(command, cwd, timeout):
    # Kill the whole process group, including an infinite student program or a
    # child of make; killing only the shell would leave local CPU consumption.
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    try:
        code = process.wait(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise
    if code:
        raise subprocess.CalledProcessError(code, command)


def export(tp, directory, ref=None):
    for name, (mode, oid) in entries(tp, ref).items():
        dest = Path(directory) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git("cat-file", "blob", oid))
        dest.chmod(0o755 if mode == "100755" else 0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tp", choices=["TP1", "TP2", "TP3", "TP4"])
    parser.add_argument("--ci", action="store_true", required=True)
    args = parser.parse_args()
    os.chdir(git("rev-parse", "--show-toplevel").decode().strip())
    with tempfile.TemporaryDirectory(prefix="ssl-tests-") as tmp:
        export(args.tp, tmp, "HEAD")
        run_suite(tmp, args.tp)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.SubprocessError, OSError) as error:
        raise SystemExit(f"Verificación fallida: {error}")
