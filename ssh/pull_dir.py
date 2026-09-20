"""从服务器目录拉取文件到本地。用法: python ssh/pull_dir.py <远端目录> <本地目录> [后缀]"""
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import target, password  # noqa: E402

remote_dir = sys.argv[1]
local_dir = Path(sys.argv[2])
local_dir.mkdir(parents=True, exist_ok=True)
suffix = sys.argv[3] if len(sys.argv) > 3 else ''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
host, port = target()
c.connect(host, port=port, username='root', password=password(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = c.open_sftp()
    count = 0
    for item in sorted(sftp.listdir_attr(remote_dir), key=lambda x: x.filename):
        if not item.filename.endswith(suffix if suffix else ''):
            continue
        if item.st_size == 0:
            continue
        sftp.get(f'{remote_dir}/{item.filename}', str(local_dir / item.filename))
        count += 1
    sftp.close()
    print(f'{count} file(s) -> {local_dir}')
finally:
    c.close()
