"""Short read-only polling probe for the active remote render."""

import paramiko

from _target import password, target


CMD = r"""date
echo ===OPTIONS===
cd /root/autodl-tmp/ComfyUI && .venv/bin/python main.py --help 2>&1 | grep -Ei 'cuda.*malloc|memory' | head -n 20 || true
ps -eo pid,stat,etime,pcpu,pmem,cmd | grep '[m]ain.py --listen 127.0.0.1 --port 8188' || true
nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total --format=csv,noheader || true
ls -lah /root/autodl-tmp/ComfyUI/output/food_ep01_control 2>&1 || true
echo ===B04===
ls -lah /root/autodl-tmp/ComfyUI/output/food_ep01_event_audition/*B04* 2>&1 || true
stat -c '%y %s %n' /root/autodl-tmp/comfyui_3d.log 2>&1 || true
stat -c '%y %s %n' /root/comfyui_stable_20260916.log 2>&1 || true
echo ===LOG_MATCHES===
grep -nEi 'error|traceback|out.of.memory|killed|exception|prompt executed|server' /root/comfyui_stable_20260916.log | tail -n 40 || true
tail -n 12 /root/comfyui_stable_20260916.log 2>&1 || true"""

host, port = target()
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username="root", password=password(), timeout=25,
               banner_timeout=25, auth_timeout=25)
try:
    _, stdout, stderr = client.exec_command(CMD, timeout=45)
    print(stdout.read().decode("utf-8", "replace"), end="")
    error = stderr.read().decode("utf-8", "replace")
    if error:
        print("STDERR:", error, end="")
finally:
    client.close()
