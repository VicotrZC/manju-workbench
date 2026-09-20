"""检查任意云主机配置。用法: python ssh/check_any_server.py <host> <port>"""
import sys
from pathlib import Path

import paramiko

ROOT = Path(r'E:\Learn\minimax-h3-cloud')
COMFY = '/root/autodl-tmp/ComfyUI'

host = sys.argv[1]
port = int(sys.argv[2])

CMDS = {
    'host': 'hostname; uptime; date',
    'gpu': 'nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version --format=csv,noheader',
    'disk': 'df -h /root/autodl-tmp | tail -1',
    'comfy_proc': "ps -eo pid,etime,cmd | grep 'main.py' | grep -v grep || echo '[not running]'",
    'comfy_http': 'curl -sf --max-time 5 http://127.0.0.1:8188/system_stats | head -c 300; echo',
    'models_h3': f"find {COMFY}/models -maxdepth 2 -type f -iname '*h3*' -o -iname '*minimax*' 2>/dev/null | sort",
    'models_qwen': f'ls -l {COMFY}/models/diffusion_models/qwen* {COMFY}/models/text_encoders/qwen_2.5* {COMFY}/models/loras/Qwen* {COMFY}/models/vae/qwen* 2>/dev/null',
    'outputs': f'ls -t {COMFY}/output 2>/dev/null | head -12',
    'custom_nodes': f"find {COMFY}/custom_nodes -maxdepth 1 -mindepth 1 -type d -printf '%f\\n' 2>/dev/null | sort",
    'project_files': f"find {COMFY} -maxdepth 2 -type f \\( -name '*motion*py' -o -name '*paradigm*py' -o -name 'h3_*api.py' \\) -printf '%p\\n' 2>/dev/null | sort",
    'h3_batch': "pgrep -af h3_batch_remote | head -2 || echo '[no h3 batch]'",
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username='root',
          password=(ROOT / 'ssh_pass.txt').read_text(encoding='utf-8').strip(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    print(f'=== connected {host}:{port} ===')
    for name, cmd in CMDS.items():
        _, o, e = c.exec_command(cmd, timeout=90)
        text = (o.read() + e.read()).decode('utf-8', 'replace').rstrip()
        print(f'--- {name} ---')
        print(text)
finally:
    c.close()
