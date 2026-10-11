#!/usr/bin/env python3
"""Refuse web-only publication unless this exact source explicitly supports it."""
from pathlib import Path
import runpy

source = Path(__file__).resolve().parents[1] / 'titan/__init__.py'
metadata = runpy.run_path(str(source))
if metadata.get('__web_update_standalone__') is not True:
    raise SystemExit('This Titan release requires a full system update; standalone web publication is disabled.')
