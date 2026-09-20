"""在云端运行一个 python 脚本并流式回显。用法: python ssh/run_remote_py.py <本地py> [超时秒]"""
import sys
import time
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import target, password  # noqa: E402

ROOT = Path(r'E:\Learn\minimax-h3-cloud')
REMOTE = '/root/autodl-tmp/ComfyUI'
local = Path(sys.argv[1])
budget = int(sys.argv[2]) if len(sys.argv) > 2 else 900

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
host, port = target()
c.connect(host, port=port, username='root', password=password(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = c.open_sftp()
    sftp.put(str(local), f'{REMOTE}/{local.name}')
    sftp.close()
    _, out, err = c.exec_command(f'cd {REMOTE} && .venv/bin/python -u {local.name}', timeout=budget + 300)
    start = time.time()
    while not out.channel.exit_status_ready():
        if out.channel.recv_ready():
            print(out.channel.recv(65536).decode('utf-8', 'replace'), end='', flush=True)
        if out.channel.recv_stderr_ready():
            print(out.channel.recv_stderr(65536).decode('utf-8', 'replace'), end='', flush=True)
        if time.time() - start > budget:
            print('--- local budget reached, leaving job running ---')
            break
        time.sleep(1)
    else:
        print(out.read().decode('utf-8', 'replace'), end='', flush=True)
        print(err.read().decode('utf-8', 'replace'), end='', flush=True)
finally:
    c.close()
