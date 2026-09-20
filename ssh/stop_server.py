#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""停服务器：取回台账与日志 → 停生成 → 停 ComfyUI → 关机。

顺序有讲究：
  1. **先取回台账与日志**（算力已经花了，记录不能丢）
  2. 杀生成脚本（否则它会继续提交任务）
  3. 杀 ComfyUI（释放显存）
  4. 最后关机（AutoDL 关机后停止计费；**不释放实例，/root/autodl-tmp 数据保留**）

★ 旧的 `ssh/shutdown_cloud.py` 里硬编码了 `port=41729`，那是过期地址。
  这里一律用 `_target()` 从 `ssh/server.txt` 读当前地址。
"""
import sys
import time
from pathlib import Path

import paramiko

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _target import target, password  # noqa: E402

OUT = Path('projects/我的系统有编制/gen/_server_records')
OUT.mkdir(parents=True, exist_ok=True)

host, port = target()
print(f'连接 {host}:{port}')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username='root', password=password(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = c.open_sftp()

    def grab(remote, local):
        try:
            sftp.get(remote, str(OUT / local))
            n = (OUT / local).stat().st_size
            print(f'  [OK] {remote} -> {local}  ({n} B)')
            return True
        except IOError as e:
            print(f'  [SKIP] {remote}: {e}')
            return False

    print('=== 1. 取回记录 ===')
    grab('/root/autodl-tmp/ComfyUI/output/ep01/ledger.jsonl', 'ledger_ep01.jsonl')
    grab('/root/gen38.log', 'gen38.log')
    grab('/root/comfy_run.log', 'comfy_run.log')
    grab('/root/previs.log', 'previs.log')

    # 产物清单（关机后无法再列）
    _, o, _ = c.exec_command(
        'ls -la /root/autodl-tmp/ComfyUI/output/ep01/*.mp4 2>/dev/null | wc -l; '
        'ls /root/autodl-tmp/ComfyUI/output/ep01/*.mp4 2>/dev/null | xargs -n1 basename')
    listing = o.read().decode('utf-8', 'replace')
    (OUT / 'server_ep01_files.txt').write_text(listing, encoding='utf-8')
    print(f'  [OK] 产物清单 -> server_ep01_files.txt')
    print('       ' + listing.strip().splitlines()[0] + ' 个片段')

    print('=== 2. 停生成脚本 ===')
    _, o, _ = c.exec_command('pkill -9 -f "gen_shots38.py" ; sleep 2; '
                             'ps aux | grep -c "[g]en_shots38"')
    print('  剩余生成进程:', o.read().decode().strip())

    print('=== 3. 停 ComfyUI ===')
    _, o, _ = c.exec_command('pkill -9 -f "ComfyUI/main.py" ; sleep 3; '
                             'ps aux | grep -c "[C]omfyUI/main.py"')
    print('  剩余 ComfyUI 进程:', o.read().decode().strip())
    _, o, _ = c.exec_command('nvidia-smi --query-gpu=memory.used --format=csv,noheader')
    print('  显存已用:', o.read().decode().strip())

    sftp.close()

    print('=== 4. 关机 ===')
    c.exec_command('shutdown -h now')
    print('  已发出关机指令（AutoDL 关机后停止计费，数据保留在 /root/autodl-tmp）')
finally:
    c.close()
