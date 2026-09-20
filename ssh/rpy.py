#!/usr/bin/env python3
"""把本地脚本以 base64 传到服务器并执行（绕开 PowerShell 引号问题）。"""
import base64
import sys
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _target import target, password  # noqa: E402

local = Path(sys.argv[1])
args = sys.argv[2:]
host, port = target()
data = base64.b64encode(local.read_bytes()).decode()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username='root', password=password(), timeout=25,
          banner_timeout=25, auth_timeout=25)
try:
    remote = f'/tmp/_{local.stem}.py'
    py = '/root/miniconda3/bin/python'
    cmd = (f'echo {data} | base64 -d > {remote} && '
           f'cd /root/autodl-tmp/ComfyUI && {py} {remote} ' + ' '.join(args))
    _, o, e = c.exec_command(cmd, timeout=3600)
    out = o.read().decode('utf-8', 'replace')
    err = e.read().decode('utf-8', 'replace')
    print(out.rstrip())
    if err.strip():
        print('--- stderr ---')
        print(err.rstrip()[:2000])
finally:
    c.close()
