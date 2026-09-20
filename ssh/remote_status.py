"""Compact read-only status probe for the active ComfyUI host."""

import paramiko

from _target import password, target


COMMAND = r"""echo ===TIME===; date
echo ===PROCESS===; ps -o pid,stat,etime,pcpu,pmem,cmd -p 2418 || true
echo ===GPU===; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader || true
echo ===OUTPUT===; ls -lah /root/autodl-tmp/ComfyUI/output/food_ep01_control 2>&1 || true
echo ===WCHAN===; cat /proc/2418/wchan 2>&1 || true; echo
echo ===STACK===; timeout 8 cat /proc/2418/stack 2>&1 | head -c 4000 || true
echo ===STATUS===; egrep '^(State|VmRSS|VmSize|voluntary_ctxt_switches|nonvoluntary_ctxt_switches):' /proc/2418/status 2>&1 || true
echo ===LOGTAIL===; timeout 12 tail -n 30 /root/autodl-tmp/comfyui_3d.log 2>&1 || true
echo ===QUEUE===; curl -sS --max-time 15 http://127.0.0.1:8188/queue 2>&1 | head -c 2000 || true; echo
echo ===HISTORY===; curl -sS --max-time 15 http://127.0.0.1:8188/history/82721e67-d5d0-4ea7-8761-2793726c595a 2>&1 | head -c 3000 || true; echo"""


host, port = target()
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username="root", password=password(), timeout=25,
               banner_timeout=25, auth_timeout=25)
try:
    _, stdout, stderr = client.exec_command(COMMAND, timeout=90)
    print(stdout.read().decode("utf-8", "replace"), end="")
    error = stderr.read().decode("utf-8", "replace")
    if error:
        print("STDERR:", error, end="")
finally:
    client.close()
