"""云主机地址读取（ssh/server.txt 为唯一配置源）。"""
from pathlib import Path

_DEFAULT_HOST = 'connect.weste.seetacloud.com'
_DEFAULT_PORT = 23181


def target():
    cfg = Path(__file__).resolve().parent / 'server.txt'
    if cfg.exists():
        parts = cfg.read_text(encoding='utf-8').split()
        if len(parts) >= 2:
            return parts[0], int(parts[1])
    return _DEFAULT_HOST, _DEFAULT_PORT


def password():
    return (Path(__file__).resolve().parent.parent / 'ssh_pass.txt').read_text(encoding='utf-8').strip()
