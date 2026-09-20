"""通用调用器：所有命令走参数调用本脚本，避免 PowerShell 内联转义错误。

见 agent.md 第二条。用法：

    python .work/run.py ssh "<远程命令>"        远程执行一条命令
    python .work/run.py sshf <本地脚本> [args]  上传脚本到远端并执行（参数按 argv 传，不经 shell）
    python .work/run.py rpy <本地脚本> [args]   同 sshf，但用远端 python3
    python .work/run.py put <本地> <远端>
    python .work/run.py get <远端> <本地>
    python .work/run.py ls <远端目录> [名字含]  列目录（**UTF-8 安全，中文名不乱码**）
    python .work/run.py getdir <远端目录> <本地tar>   整目录流式打包拉回（不占服务器磁盘）
    python .work/run.py untar <本地tar> [目标目录]     解包（**强制 UTF-8，中文名不乱码**）
    python .work/run.py untar <本地tar> --list        只列内容，不解
    python .work/run.py py <本地脚本> [args]    本机执行 python 脚本
    python .work/run.py ff <ffmpeg 参数...>
    python .work/run.py git <git 参数...>
    python .work/run.py probe                   服务器 + ComfyUI + GPU 快照

设计原则：参数只经过 argv，不经过任何 shell 引号解析（远端命令除外，它本身就是一条 shell 命令，
但由调用方整条传入，PowerShell 侧不需要转义）。
"""
import io
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 控制台默认是 GBK，中文名/中文输出会乱码。统一改 UTF-8。
# 2026-09-20：`ssh "ls -l"` 拿中文文件名一直是乱码，根因就是这个。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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


def cmd_ls(argv):
    """列远程目录。**走 SFTP listdir，不经 shell** —— 所以中文文件名不会变成乱码。

    2026-09-20 加：`ssh "ls -l"` 遇到中文名会输出乱码（远端 locale 非 UTF-8），
    而 SFTP 的 listdir 是二进制安全的，名字原样回来。
    """
    if not argv:
        print("usage: ls <remote dir> [name-substring]")
        return 2
    d = argv[0]
    needle = argv[1] if len(argv) > 1 else ""
    c, _h, _p = ssh_client()
    try:
        s = c.open_sftp()
        rows = []
        for a in s.listdir_attr(d):
            if needle and needle not in a.filename:
                continue
            rows.append((a.st_mtime, a.st_size, a.filename))
        s.close()
        rows.sort(reverse=True)
        for mt, size, name in rows:
            print("%s  %10d  %s" % (time.strftime("%m-%d %H:%M", time.localtime(mt)),
                                    size, name))
        return 0
    finally:
        c.close()


def shlex_quote(s):
    """POSIX 单引号转义。远端路径可能含中文/空格，必须引起来。"""
    return "'" + str(s).replace("'", "'\\''") + "'"


def cmd_getdir(argv):
    """整目录拉回：远端 `tar cf -` 直接流进本地文件。

    为什么不先打包再 get：服务器 /dev/md0 常年只剩几 G，2.5 G 的中间 tar
    很容易把盘写满，连带把 ComfyUI 弄挂。流式传输不落远端盘，且一个 TCP
    流比几百次 SFTP 往返快得多。
    """
    if len(argv) != 2:
        print("usage: getdir <remote dir> <local tar>")
        return 2
    remote, local = argv[0].rstrip("/"), Path(argv[1])
    local.parent.mkdir(parents=True, exist_ok=True)
    # 远端路径必须按 POSIX 字符串切，不能用 pathlib.Path：
    # Windows 上 Path("/root/x") 会变成 "\root\x"，远端 tar 直接找不到。
    parent, _, base = remote.rpartition("/")
    if not base:
        print("remote dir must be an absolute POSIX path:", remote)
        return 2
    # -C 到父目录再打包 basename，tar 里就是一层的名字，解开不会散落
    cmd = "tar cf - -C %s %s" % (shlex_quote(parent), shlex_quote(base))
    c, _h, _p = ssh_client()
    try:
        _in, out, err = c.exec_command(cmd)
        n = 0
        t0 = time.time()
        with open(local, "wb") as fh:
            while True:
                buf = out.read(1 << 20)
                if not buf:
                    break
                fh.write(buf)
                n += len(buf)
                if n % (64 << 20) < (1 << 20):
                    print("  ...%d MB  %.1f MB/s" % (n >> 20, (n >> 20) / max(time.time() - t0, .01)))
        e = err.read().decode("utf-8", "replace").strip()
        rc = out.channel.recv_exit_status()
        print("getdir %s -> %s  %.1f MB  %.1f MB/s  rc=%d"
              % (remote, local, n / 1048576, (n / 1048576) / max(time.time() - t0, .01), rc))
        if e:
            print("stderr:", e[:2000])
        return rc
    finally:
        c.close()


def cmd_untar(argv):
    """解包，**强制按 UTF-8 解文件名**。

    2026-09-20 踩坑：`getdir` 拉回来的包里中文名是对的（GNU tar 存原始字节），
    但 Windows 自带的 `tar -xf` 会按系统 ANSI 代码页（简中是 GBK/936）解码文件名，
    于是 `cc_年轻人_bust.png` 落盘成 `cc_骞磋交浜篲bust.png` —— 图还在，名字废了，
    而且**不报任何错**。这类"静默损坏"正是规矩.md §8 要防的东西。
    所以解包一律走 Python 的 tarfile（UTF-8），不要用系统 tar。
    """
    if not argv:
        print("usage: untar <tar> [dest dir | --list]")
        return 2
    src = Path(argv[0])
    if not src.exists():
        print("missing", src)
        return 1
    listing = len(argv) > 1 and argv[1] == "--list"
    dest = None if listing else Path(argv[1]) if len(argv) > 1 else src.with_suffix("")
    import tarfile
    try:
        tf = tarfile.open(src, "r:", encoding="utf-8", errors="surrogateescape")
    except Exception as exc:
        print("打不开:", exc)
        return 1
    with tf:
        n = 0
        for m in tf:
            if listing:
                print("%s%12d  %s" % ("d " if m.isdir() else "  ", m.size, m.name))
            else:
                # filter="data" 是 3.12+ 的默认安全策略；老版本没有这个参数
                try:
                    tf.extract(m, dest, filter="data")
                except TypeError:
                    tf.extract(m, dest)
                n += 1
        if not listing:
            print("untar %s -> %s  (%d 条)" % (src, dest, n))
    return 0


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
    if sub in ("ls", "ll"):
        return cmd_ls(argv)
    if sub == "getdir":
        return cmd_getdir(argv)
    if sub == "untar":
        return cmd_untar(argv)
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
