#!/usr/bin/env python3
"""Desde la raíz: python3 verificar_tp.py TP3 (después de git add TP3)."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parent / ".github/scripts/local_receipt.py"), run_name="__main__")
