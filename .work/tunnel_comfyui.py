"""本地到云端 ComfyUI 的 SSH 隧道（paramiko 实现，等价于 ssh -L）。

用法：
    .venv/bin/python .work/tunnel_comfyui.py [本地端口] [远端端口]
默认：本地 127.0.0.1:8188  ->  云端 127.0.0.1:8188

地址取 ssh/server.txt，密码取 ssh_pass.txt；密码不打印、不写日志、不入库。
只做端口转发，不在云端启动、停止或修改任何东西。
"""
import io
import select
import socket
import sys
import threading
import time
from pathlib import Path

import paramiko

# 中文输出统一 UTF-8。走 run_tunnel_daemon.py 时 stdout 已被重定向到 tunnel.log
# （那边显式 encoding="utf-8"），但**直接跑本脚本**时控制台是 GBK，[warn]/[reconnect]
# 会变乱码 —— 而这两行恰恰是排查隧道断连时唯一能看的线索。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = (ROOT / 'ssh' / 'server.txt').read_text(encoding='utf-8').split()[:2]
LOCAL_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8188
REMOTE_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8188
REMOTE_HOST = '127.0.0.1'


def pump(src, dst):
    """单向搬运数据，直到任一端关闭。"""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        for obj in (dst, src):
            try:
                obj.close()
            except Exception:
                pass


def handle(conn, transport):
    try:
        chan = transport.open_channel(
            'direct-tcpip', (REMOTE_HOST, REMOTE_PORT), conn.getpeername(), timeout=15)
    except Exception as exc:
        print(f'[warn] 打开远端通道失败: {type(exc).__name__}: {exc}', flush=True)
        conn.close()
        return
    threading.Thread(target=pump, args=(conn, chan), daemon=True).start()
    threading.Thread(target=pump, args=(chan, conn), daemon=True).start()


def connect():
    pw = (ROOT / 'ssh_pass.txt').read_text(encoding='utf-8').strip()
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=int(PORT), username='root', password=pw,
                timeout=20, banner_timeout=25, auth_timeout=25,
                allow_agent=False, look_for_keys=False)
    return cli


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', LOCAL_PORT))
    srv.listen(64)

    cli = None
    while True:
        try:
            if cli is None:
                cli = connect()
                cli.get_transport().set_keepalive(30)
                print(f'READY  http://127.0.0.1:{LOCAL_PORT}  ->  {HOST}:{PORT} -> '
                      f'{REMOTE_HOST}:{REMOTE_PORT}', flush=True)
            transport = cli.get_transport()
            if not transport or not transport.is_active():
                raise ConnectionError('transport 已断开')
            r, _, _ = select.select([srv], [], [], 2.0)
            if r:
                conn, _ = srv.accept()
                handle(conn, transport)
        except Exception as exc:
            print(f'[reconnect] {type(exc).__name__}: {exc} — 5 秒后重连', flush=True)
            try:
                if cli:
                    cli.close()
            except Exception:
                pass
            cli = None
            time.sleep(5)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
