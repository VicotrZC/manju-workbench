"""启动当前 ssh/server.txt 指向的 ComfyUI，并等待 API 就绪。"""
import sys
import time
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import password, target  # noqa: E402

COMFY = "/root/autodl-tmp/ComfyUI"
START = f"{COMFY}/start_comfy_ck.sh"
LOG = f"{COMFY}/comfy_start.log"


def run(client, command, timeout=60):
    _, out, err = client.exec_command(command, timeout=timeout)
    return (out.read() + err.read()).decode("utf-8", "replace")


host, port = target()
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username="root", password=password(),
               timeout=25, banner_timeout=25, auth_timeout=25)
try:
    stats = run(client, "curl -sf --max-time 4 http://127.0.0.1:8188/system_stats")
    if not stats.strip():
        print(f"Launching ComfyUI on {host}:{port} ...", flush=True)
        run(client, f"cd {COMFY} && setsid bash {START} </dev/null >{LOG} 2>&1 &")
        for elapsed in range(5, 301, 5):
            time.sleep(5)
            stats = run(client, "curl -sf --max-time 4 http://127.0.0.1:8188/system_stats")
            if stats.strip():
                print(f"READY after about {elapsed}s")
                break
            if elapsed % 30 == 0:
                print(run(client, f"tail -8 {LOG}"), flush=True)
        else:
            raise RuntimeError("ComfyUI did not become ready within 300 seconds")
    else:
        print("ALREADY READY")
    print(stats[:1000])
    print(run(client, "nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader"))
    print(run(client, "curl -sf --max-time 5 http://127.0.0.1:8188/queue"))
finally:
    client.close()
