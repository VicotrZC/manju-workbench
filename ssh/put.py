#!/usr/bin/env python3
"""把本地文件传到服务器指定路径。用法: python ssh/put.py <本地> <远端绝对路径>"""
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import target, password  # noqa: E402

local, remote = Path(sys.argv[1]), sys.argv[2]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
host, port = target()
c.connect(host, port=port, username='root', password=password(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = c.open_sftp()
    sftp.put(str(local), remote)
    st = sftp.stat(remote)
    print(f'[OK] {local.name} -> {remote}  ({st.st_size} B)')
    sftp.close()
finally:
    c.close()
