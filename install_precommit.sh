#!/usr/bin/env bash

set -e

echo "Instalando dependencias..."

if command -v apt >/dev/null 2>&1; then
  echo "Detectado: Ubuntu/Debian"
  sudo apt update
  sudo apt install -y python3 python3-pip clang-format cppcheck

elif command -v brew >/dev/null 2>&1; then
  echo "Detectado: macOS"
  brew install python clang-format cppcheck

else
  echo "Sistema no soportado automáticamente."
  exit 1
fi

echo "Instalando pre-commit..."
pip3 install pre-commit

echo "Instalando hooks..."
pre-commit install

echo "Verificando instalación..."
python3 --version
pre-commit --version
clang-format --version
cppcheck --version

echo "Instalación completa."
