#!/usr/bin/env bash

set -euo pipefail

if (($# == 0)); then
  echo "Uso: $0 <paquete> [<paquete> ...]" >&2
  exit 2
fi

# Evita que un mirror o un lock de apt bloquee el runner hasta el límite
# predeterminado de GitHub Actions (360 minutos).
readonly COMMAND_TIMEOUT="${APT_COMMAND_TIMEOUT:-4m}"
readonly APT_RETRIES="${APT_RETRIES:-3}"
readonly APT_NETWORK_TIMEOUT="${APT_NETWORK_TIMEOUT:-20}"
readonly APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-60}"

apt_options=(
  -o "Acquire::Retries=${APT_RETRIES}"
  -o "Acquire::http::Timeout=${APT_NETWORK_TIMEOUT}"
  -o "Acquire::https::Timeout=${APT_NETWORK_TIMEOUT}"
  -o "DPkg::Lock::Timeout=${APT_LOCK_TIMEOUT}"
)

run_apt() {
  sudo timeout --signal=TERM --kill-after=10s "${COMMAND_TIMEOUT}" \
    env DEBIAN_FRONTEND=noninteractive \
    apt-get "${apt_options[@]}" "$@"
}

echo "Actualizando índices de apt (timeout: ${COMMAND_TIMEOUT})..."
run_apt update -qq

echo "Instalando paquetes: $*"
run_apt install -y --no-install-recommends "$@"
