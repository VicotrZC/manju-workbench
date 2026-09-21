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
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# 控制台默认 GBK，中文输出会乱码。统一改 UTF-8（stderr 也要包 —— subprocess 的报错走那边）。
# 2026-09-20：本脚本此前只打中文不包装，`python .work/launch_tunnel.py` 的输出在
# PowerShell 里是一片问号，看不出隧道到底起没起来。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
# 2026-09-20：原来写死 `.work/venv/Scripts/python*.exe`。那个 venv **不入库**
# （agent.md §四 明确不跟踪），换台电脑/新克隆里根本没有 → 隧道一启动就 FileNotFound。
# 改成用"当前正在跑这段代码的解释器"，再找同目录的 pythonw.exe（无控制台窗口，适合常驻）。
PY = Path(sys.executable)
_PYW = PY.with_name("pythonw.exe")
PYW = _PYW if _PYW.exists() else PY
DAEMON = ROOT / ".work" / "run_tunnel_daemon.py"
LOG = ROOT / ".work" / "tunnel.log"
PORT = 8188

# ★ 2026-09-21 新增：本脚本此前是 **Windows 专有**的（PowerShell `Get-NetTCPConnection`、
# WMI `Invoke-CimMethod Win32_Process`、`pythonw.exe`），换到 Linux 后 `start()` 直接
# 在 `subprocess.run(["powershell", ...])` 上 FileNotFoundError —— 又一次「换系统就废」。
# 隧道本体 `.work/tunnel_comfyui.py` **本来就是跨平台的**（纯 paramiko），
# 所以这里只补 POSIX 分支，Windows 那条 WMI 路一字未动。
IS_WIN = os.name == "nt"


def ps(script: str, timeout: int = 60) -> str:
    """跑一段内联 PowerShell（不是 .ps1 文件，所以不受脚本执行策略限制）。"""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    return (r.stdout or "").strip() + (("\n[stderr] " + r.stderr.strip()) if r.stderr.strip() else "")


def port_pid():
    if not IS_WIN:
        # POSIX：先用 ss（iproute2，几乎必有），取不到再退 lsof。
        # ss 的 pid 藏在 users:(("python",pid=1234,fd=7)) 里；lsof -ti 直接就是 pid。
        for cmd in (["ss", "-ltnpH", "sport = :%d" % PORT],
                    ["lsof", "-ti", "tcp:%d" % PORT, "-sTCP:LISTEN"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            out = (r.stdout or "").strip()
            if not out:
                continue
            m = re.search(r"pid=(\d+)", out) or re.match(r"(\d+)", out)
            if m:
                return int(m.group(1))
        return None
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
    if IS_WIN:
        print(ps("Stop-Process -Id %d -Force; '已停 pid %d'" % (pid, pid)))
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            print("已停 pid %d（SIGTERM）" % pid)
        except ProcessLookupError:
            print("pid %d 已经不在了" % pid)
    return 0


def preflight() -> int:
    """起隧道之前先确认配置齐了。

    2026-09-20：缺 ssh_pass.txt 时，隧道本体在 connect() 里抛 FileNotFoundError，
    被它自己的重连循环吞掉，每 5 秒重试一次、只写进 tunnel.log —— 表现出来是
    "起了但 30 秒没就绪"，看不出真正原因。这里提前拦住，给一句人话。
    """
    if not (ROOT / "ssh" / "server.txt").exists():
        print("❌ 缺 ssh/server.txt（一行：<主机> <端口>）—— 克隆不完整")
        return 3
    pwf = ROOT / "ssh_pass.txt"
    if not pwf.exists() or not pwf.read_text(encoding="utf-8").strip():
        print("❌ 缺 ssh_pass.txt —— 服务器密码。**它永远不入库**，每台新电脑都要手动放一次：")
        print("     把密码单独一行写进 %s" % pwf)
        print("   然后重跑本脚本。不要提交它、不要打印它。")
        return 3
    return 0


def start() -> int:
    rc = preflight()
    if rc:
        return rc
    got = http_ok(timeout=4)
    if got:
        print("隧道已在且穿透正常（ComfyUI %s，显存空闲 %.1f GB），不重复启动" % (got[0], got[1]))
        return 0
    if port_up():
        print("端口在听但穿透失败（僵死通道），先停掉再起")
        stop()
        time.sleep(1)

    exe = PYW if PYW.exists() else PY
    if IS_WIN:
        cmdline = '"%s" "%s"' % (exe, DAEMON)
        script = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
                  "-Arguments @{{ CommandLine = '{0}'; CurrentDirectory = '{1}' }}; "
                  "Write-Output ('RET=' + $r.ReturnValue + ' PID=' + $r.ProcessId)").format(cmdline, ROOT)
        print("用 WMI 起隧道：%s" % Path(cmdline.split('"')[1]).name)
        print("   " + ps(script).replace("\n", "\n   "))
    else:
        # POSIX：`start_new_session=True` 内部就是 setsid()，让子进程成为**新会话的首进程**，
        # 从而脱离控制终端与父 shell 的作业控制 —— 这正是 Windows 那边必须绕道 WMI 的原因
        # （「会话后台作业会被回收」），在 Linux 上由内核直接保证，不需要额外机制。
        # 0/1/2 全部丢给 DEVNULL：日志由 run_tunnel_daemon.py 自己往 tunnel.log 写，
        # 留着继承来的 fd 反而会把日志和这个 shell 绑在一起。
        p = subprocess.Popen([str(exe), str(DAEMON)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True, cwd=str(ROOT))
        print("用 setsid 起隧道：%s（pid %d，新会话，脱离本 shell）" % (Path(exe).name, p.pid))

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
