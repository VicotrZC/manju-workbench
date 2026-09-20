"""通用调用器：所有命令走参数调用本脚本，避免 PowerShell 内联转义错误。

见 agent.md 第二条。用法：

    python .work/run.py ssh "<远程命令>"        远程执行一条命令
    python .work/run.py sshf <本地脚本> [args]  上传脚本到远端并执行（参数按 argv 传，不经 shell）
    python .work/run.py rpy <本地脚本> [args]   同 sshf，但用远端 python3
    python .work/run.py put <本地> <远端>
    python .work/run.py get <远端> <本地>
    python .work/run.py py <本地脚本> [args]    本机执行 python 脚本
    python .work/run.py ff <ffmpeg 参数...>
    python .work/run.py git <git 参数...>
    python .work/run.py probe                   服务器 + ComfyUI + GPU 快照

设计原则：参数只经过 argv，不经过任何 shell 引号解析（远端命令除外，它本身就是一条 shell 命令，
但由调用方整条传入，PowerShell 侧不需要转义）。
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".work" / "venv" / "Scripts" / "python.exe"
FFMPEG = ROOT / "tools" / "ffmpeg.exe"


def ssh_client():
    import paramiko
    host, port = (ROOT / "ssh" / "server.txt").read_text(encoding="utf-8").split()[:2]
    pw = (ROOT / "ssh_pass.txt").read_text(encoding="utf-8").strip()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=int(port), username="root", password=pw, timeout=25,
              allow_agent=False, look_for_keys=False)
    return c, host, port


def cmd_ssh(argv):
    if not argv:
        print("usage: ssh <remote command>")
        return 2
    c, _h, _p = ssh_client()
    try:
        _i, o, e = c.exec_command(argv[0], timeout=int(argv[1]) if len(argv) > 1 else 600)
        out = o.read().decode("utf-8", "replace")
        err = e.read().decode("utf-8", "replace")
        sys.stdout.write(out)
        if err.strip():
            sys.stdout.write("\n[stderr]\n" + err)
        return 0
    finally:
        c.close()


def cmd_put(argv):
    if len(argv) != 2:
        print("usage: put <local> <remote>")
        return 2
    c, _h, _p = ssh_client()
    try:
        s = c.open_sftp()
        s.put(argv[0], argv[1])
        print("put %s -> %s" % (argv[0], argv[1]))
        s.close()
        return 0
    finally:
        c.close()


def cmd_get(argv):
    if len(argv) != 2:
        print("usage: get <remote> <local>")
        return 2
    Path(argv[1]).parent.mkdir(parents=True, exist_ok=True)
    c, _h, _p = ssh_client()
    try:
        s = c.open_sftp()
        s.get(argv[0], argv[1])
        print("get %s -> %s" % (argv[0], argv[1]))
        s.close()
        return 0
    finally:
        c.close()


def _remote_py(argv, python):
    if not argv:
        print("usage: rpy <local.py> [args...]")
        return 2
    local = Path(argv[0])
    if not local.exists():
        print("missing", local)
        return 1
    c, _h, _p = ssh_client()
    try:
        s = c.open_sftp()
        remote = "/root/" + local.name
        s.put(str(local), remote)
        s.close()
        import shlex
        cmd = "%s %s %s" % (python, remote, " ".join(shlex.quote(a) for a in argv[1:]))
        _i, o, e = c.exec_command(cmd, timeout=7200)
        sys.stdout.write(o.read().decode("utf-8", "replace"))
        err = e.read().decode("utf-8", "replace")
        if err.strip():
            sys.stdout.write("\n[stderr]\n" + err)
        return 0
    finally:
        c.close()


def cmd_probe(_argv):
    c, host, port = ssh_client()
    try:
        checks = [
            ("server", "date +%F' '%T; uptime | cut -c1-60"),
            ("gpu", "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu "
                    "--format=csv,noheader"),
            ("gpu procs", "nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader"),
            ("disk", "df -h / /root/autodl-tmp | tail -2"),
            ("comfy", "curl -s -m 6 http://127.0.0.1:8188/system_stats | head -c 120; echo; "
                      "curl -s -m 6 http://127.0.0.1:8188/queue"),
        ]
        print("target %s:%s" % (host, port))
        for label, cmd in checks:
            _i, o, _e = c.exec_command(cmd, timeout=120)
            print("\n=== %s ===\n%s" % (label, o.read().decode("utf-8", "replace").rstrip()))
        return 0
    finally:
        c.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sub, argv = sys.argv[1], sys.argv[2:]
    if sub == "ssh":
        return cmd_ssh(argv)
    if sub == "put":
        return cmd_put(argv)
    if sub == "get":
        return cmd_get(argv)
    if sub == "sshf":
        return _remote_py(argv, "python3")
    if sub == "rpy":
        return _remote_py(argv, "python3")
    if sub == "py":
        return subprocess.run([str(PY)] + argv).returncode
    if sub == "ff":
        return subprocess.run([str(FFMPEG)] + argv).returncode
    if sub == "git":
        return subprocess.run(["git"] + argv, cwd=str(ROOT)).returncode
    if sub == "probe":
        return cmd_probe(argv)
    print("unknown subcommand:", sub)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
