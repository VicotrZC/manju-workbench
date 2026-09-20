"""Daemon wrapper: redirects its own output to log files, then runs the tunnel.

Used so the process can be started by WMI with no shell involved (cmd.exe /c
quoting mangled the redirects). Keeps the tunnel alive independently of any
session or shell process tree.
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / ".work" / "tunnel.log"

# line-buffered so progress is visible while it runs
fh = open(LOG, "a", encoding="utf-8", buffering=1)
sys.stdout = fh
sys.stderr = fh

print("=== launcher start ===", flush=True)
runpy.run_path(str(ROOT / ".work" / "tunnel_comfyui.py"), run_name="__main__")
