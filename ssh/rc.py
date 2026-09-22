"""通用远程命令执行器：python ssh/rc.py "<命令>"（地址读 ssh/server.txt）"""
import sys
from pathlib import Path

import paramiko

# ⚠️ **必须在任何 print 之前**（2026-09-22 修）。
# Windows 控制台默认 GBK，而远端脚本常打 ✓/✅ 之类的字符，
# 于是 `print(out)` 抛 UnicodeEncodeError: 'gbk' codec can't encode character '\u2713' ——
# 命令其实**跑成功了**，却因为打印不出来而报失败，很容易被误读成"远端出错"。
# errors='replace' 保证**再怪的字符也不会把整条结果吞掉**。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import target, password  # noqa: E402

cmd = ' '.join(sys.argv[1:])
if not cmd:
    print('usage: python ssh/rc.py "<remote command>"')
    raise SystemExit(2)

host, port = target()
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(host, port=port, username='root', password=password(),
          timeout=25, banner_timeout=25, auth_timeout=25)
try:
    _, o, e = c.exec_command(cmd, timeout=3600)
    out = o.read().decode('utf-8', 'replace')
    err = e.read().decode('utf-8', 'replace')
    print(out.rstrip())
    if err.strip():
        print('--- stderr ---')
        print(err.rstrip())
finally:
    c.close()
