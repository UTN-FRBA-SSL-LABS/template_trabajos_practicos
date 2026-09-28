#!/bin/sh
# Infraestructura docente: make compila el verificador C, sin Python local.
set -eu
case "${1:-}" in TP1|TP2|TP3|TP4) tp=$1 ;; *) echo 'Uso: make -C TPN verificar' >&2; exit 1 ;; esac
cd "$(git rev-parse --show-toplevel)"
# Invalidar incluso si falla la compilación del propio verificador.
printf '{"result":"failed","tp":"%s"}\n' "$tp" > "$tp/.verificacion-local.json"
ssl_tmp=$(mktemp -d "${TMPDIR:-/tmp}/ssl-verificar.XXXXXXXX")
trap 'rm -rf "$ssl_tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cc -std=c11 -O2 -Wall -Wextra -Werror .github/scripts/local_verifier.c -o "$ssl_tmp/verificar"
"$ssl_tmp/verificar" "$tp" "$ssl_tmp/entrega"
