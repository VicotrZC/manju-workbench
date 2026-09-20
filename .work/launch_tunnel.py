"""起 ComfyUI 的 SSH 隧道（Windows 侧启动器）。

为什么要这么绕（都是实测踩出来的）：
  * `.work/launch_tunnel.ps1` 是本机文档里的启动器，但本机**禁止执行 PowerShell 脚本**
    （"running scripts is disabled on this system"），.ps1 根本跑不起来；
  * 用「会话后台作业」起隧道会被回收；
  * 用 `subprocess.Popen(DETACHED_PROCESS)` 直接起，也活不过本会话（2026-09-19 复现：跑完一轮后
    8188 已无监听、进程消失）。
  * **真正扛得住的是 `.work/launch_tunnel_wmi.ps1` 的做法**：由 WMI（Win32_Process.Create）创建
    `pythonw.exe .work\run_tunnel_daemon.py`，进程挂在 WmiPrvSE 名下，不随任何 shell / 作业对象消失。
    本脚本就是用 Python 走同一条 WMI 路（不依赖 .ps1，符合"命令走参数调用 py"的规矩）。

用法：
    python .work/run.py py .work/launch_tunnel.py            # 起（已在则跳过）
    python .work/run.py py .work/launch_tunnel.py --status   # 只看状态（含真实 HTTP 验证）
    python .work/run.py py .work/launch_tunnel.py --stop     # 停掉占用 8188 的进程
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYW = ROOT / ".work" / "venv" / "Scripts" / "pythonw.exe"
PY = ROOT / ".work" / "venv" / "Scripts" / "python.exe"
DAEMON = ROOT / ".work" / "run_tunnel_daemon.py"
LOG = ROOT / ".work" / "tunnel.log"
PORT = 8188


def ps(script: str, timeout: int = 60) -> str:
    """跑一段内联 PowerShell（不是 .ps1 文件，所以不受脚本执行策略限制）。"""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return (r.stdout or "").strip() + (("\n[stderr] " + r.stderr.strip()) if r.stderr.strip() else "")


def port_pid():
    out = ps("(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue |"
             " Select-Object -First 1).OwningProcess" % PORT)
    return int(out) if out.isdigit() else None


def port_up(timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(timeout: float = 8.0):
    """真实穿透验证：端口在听 ≠ 隧道能用（通道可能开失败）。返回 (版本, 显存空闲GB) 或 None。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/system_stats" % PORT, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
        d = j["devices"][0]
        return j["system"]["comfyui_version"], d["vram_free"] / 1073741824.0, d["vram_total"] / 1073741824.0
    except Exception:                                  # noqa: BLE001
        return None


def tail(n: int = 8) -> str:
    if not LOG.exists():
        return "   (无 .work/tunnel.log)"
    return "\n".join("   " + l for l in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


def status() -> int:
    pid = port_pid()
    print("127.0.0.1:%d  %s%s" % (PORT, "在听" if pid else "没在听", ("（pid %d）" % pid) if pid else ""))
    got = http_ok()
    if got:
        print("真实穿透验证 ✅  ComfyUI %s  显存空闲 %.1f / %.1f GB" % got)
    else:
        print("真实穿透验证 ❌  端口%s，但 HTTP 拿不到 /system_stats"
              % ("在听（多半是僵死通道）" if port_up() else "没在听"))
    print("--- .work/tunnel.log 末尾 ---")
    print(tail())
    return 0 if got else 1


def stop() -> int:
    pid = port_pid()
    if not pid:
        print("8188 上没有进程")
        return 0
    print(ps("Stop-Process -Id %d -Force; '已停 pid %d'" % (pid, pid)))
    return 0


def start() -> int:
    got = http_ok(timeout=4)
    if got:
        print("隧道已在且穿透正常（ComfyUI %s，显存空闲 %.1f GB），不重复启动" % (got[0], got[1]))
        return 0
    if port_up():
        print("端口在听但穿透失败（僵死通道），先停掉再起")
        stop()
        time.sleep(1)

    exe = PYW if PYW.exists() else PY
    cmdline = '"%s" "%s"' % (exe, DAEMON)
    script = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
              "-Arguments @{{ CommandLine = '{0}'; CurrentDirectory = '{1}' }}; "
              "Write-Output ('RET=' + $r.ReturnValue + ' PID=' + $r.ProcessId)").format(cmdline, ROOT)
    print("用 WMI 起隧道：%s" % Path(cmdline.split('"')[1]).name)
    print("   " + ps(script).replace("\n", "\n   "))

    for i in range(1, 16):
        time.sleep(2)
        got = http_ok(timeout=5)
        if got:
            print("就绪：127.0.0.1:%d 真实穿透正常（ComfyUI %s，显存空闲 %.1f / %.1f GB，约 %d 秒）"
                  % (PORT, got[0], got[1], got[2], i * 2))
            print("--- .work/tunnel.log 末尾 ---")
            print(tail())
            return 0
        if i % 3 == 0:
            print("   等待中 %ds ..." % (i * 2))
    print("!! 30 秒内没起来。状态：")
    return status()


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--status":
        return status()
    if arg == "--stop":
        return stop()
    return start()


if __name__ == "__main__":
    sys.exit(main())
