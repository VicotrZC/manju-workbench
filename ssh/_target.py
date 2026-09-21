"""云主机地址读取（ssh/server.txt 为唯一配置源）。"""
from pathlib import Path

_DEFAULT_HOST = 'connect.weste.seetacloud.com'
_DEFAULT_PORT = 23181


def _read_text(p: Path) -> str:
    """**必须容忍 BOM。**

    2026-09-21 实测踩到：用 PowerShell `Set-Content -Encoding UTF8` 改 `server.txt`
    会写入 BOM，而 `encoding='utf-8'` 不剥它 —— BOM 于是变成主机名的第一个字符，
    报 `UnicodeEncodeError: 'gbk' codec can't encode character '\\ufeff'`。
    主机名是**每次开机都会变**的东西，谁来编辑都可能用 Windows 工具，
    所以这里兜住，而不是要求编辑者记得别加 BOM。
    """
    return p.read_text(encoding='utf-8-sig')


def target():
    cfg = Path(__file__).resolve().parent / 'server.txt'
    if cfg.exists():
        parts = _read_text(cfg).split()
        if len(parts) >= 2:
            return parts[0].lstrip('\ufeff'), int(parts[1])
    return _DEFAULT_HOST, _DEFAULT_PORT


def password():
    return _read_text(Path(__file__).resolve().parent.parent / 'ssh_pass.txt').strip()
