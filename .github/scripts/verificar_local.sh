#!/bin/sh
# Infraestructura docente: make compila el verificador C, sin Python local.
set -eu
case "${1:-}" in TP1|TP2|TP3|TP4) tp=$1 ;; *) echo 'Uso: make -C TPN verificar' >&2; exit 1 ;; esac
cd "$(git rev-parse --show-toplevel)"
ssl_root=$(pwd -P)
ssl_cc=${2:-gcc}
ssl_make=${3:-make}
ssl_exeext=${4:-}
# Invalidar incluso si falla la compilación del propio verificador.
printf '{"result":"failed","tp":"%s"}\n' "$tp" > "$tp/.verificacion-local.json"
ssl_tmp=$(mktemp -d "${TMPDIR:-/tmp}/ssl-verificar.XXXXXXXX")
trap 'rm -rf "$ssl_tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ssl_work="$ssl_tmp/entrega"
ssl_helper="$ssl_tmp/verificar$ssl_exeext"
# Identificar el destino del compilador, no confundir MinGW nativo con Cygwin.
ssl_macros=$(printf '\n' | "$ssl_cc" -dM -E -x c -)
ssl_unicode=
if printf '%s\n' "$ssl_macros" | grep -q '^#define _WIN32 '; then
    if ! printf '%s\n' "$ssl_macros" | grep -Eq '^#define (__CYGWIN__|__MSYS__) '; then
        ssl_unicode=-municode
        ssl_helper="$ssl_tmp/verificar.exe"
        # Los programas Windows reciben rutas Windows; sh conserva sus rutas Unix.
        ssl_root=$(cygpath -m "$ssl_root")
        ssl_work=$(cygpath -m "$ssl_work")
        ssl_make=$(cygpath -m "$(command -v "$ssl_make")")
        ssl_cc=$(cygpath -m "$(command -v "$ssl_cc")")
    fi
fi
"$ssl_cc" -std=c11 -O2 -Wall -Wextra -Werror ${ssl_unicode:+$ssl_unicode} .github/scripts/local_verifier.c -o "$ssl_helper"
"$ssl_helper" "$tp" "$ssl_work" "$ssl_root" "$ssl_make" "$ssl_cc" "$ssl_exeext"
