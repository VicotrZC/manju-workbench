"""Upload approved source assets to the isolated Qwen-Image 2.1 ComfyUI input folder."""

import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ssh"))
from _target import password, target  # noqa: E402

PROJECT = ROOT / "projects" / "美食：全市巡摆，馋哭食客"
REMOTE_DIR = "/root/autodl-tmp/ComfyUI-qwen21/input"
FILES = {
    "Q21_SRC_CHR01_body.png": "assets/CHR/PRODUCTION/C01_body_master.png",
    "Q21_SRC_CHR01_face.png": "assets/CHR/PRODUCTION/C01_head_three_quarter_master.png",
    "Q21_SRC_CHR02_vendor.png": "assets/CHR/PRODUCTION/C04_body_master_codex_v1.png",
    "Q21_SRC_EBIKE.png": "assets/PRP/PRP-02_ebike_master.png",
    "Q21_SRC_STALL.png": "assets/SCN/API_LOCK_V1/SCN01_pork_stall_master.png",
    "Q21_SRC_STREET.png": "assets/SCN/SCN-02_street_master.png",
    "Q21_SRC_MARKET_ENTRY.png": "assets/SCN/SCN-03_market_entry_master_codex_v1.png",
    "Q21_SRC_PORK.png": "assets/PRP/PRP-03_black_pork_codex_v1.png",
    "Q21_SRC_PHONE.png": "assets/PRP/PRP-01_phone_pig_video_codex_v1.png",
    "Q21_ASSET_CHR01_BODY.png": "assets/CHR/QWEN21_V1/CHR01_body_qwen21_v1.png",
    "Q21_ASSET_CHR01_FACE.png": "assets/CHR/QWEN21_V1/CHR01_face_qwen21_v1.png",
    "Q21_ASSET_CHR02_VENDOR.png": "assets/CHR/QWEN21_V1/CHR02_vendor_qwen21_v1.png",
    "Q21_ASSET_EBIKE.png": "assets/PRP/QWEN21_V1/PRP02_ebike_qwen21_v1.png",
    "Q21_ASSET_STALL.png": "assets/SCN/QWEN21_V1/SCN01_pork_stall_qwen21_v1.png",
    "Q21_ASSET_STREET.png": "assets/SCN/QWEN21_V1/SCN02_street_qwen21_v1.png",
    "Q21_ASSET_MARKET_ENTRY.png": "assets/SCN/QWEN21_V1/SCN03_market_entry_qwen21_v1.png",
    "Q21_ASSET_PORK.png": "assets/PRP/QWEN21_V1/PRP03_black_pork_qwen21_v1.png",
    "Q21_ASSET_PHONE.png": "assets/PRP/QWEN21_V1/PRP01_phone_qwen21_v1.png",
}

host, port = target()
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username="root", password=password(), timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = client.open_sftp()
    for remote_name, relative in FILES.items():
        source = PROJECT / relative
        destination = f"{REMOTE_DIR}/{remote_name}"
        sftp.put(str(source), destination)
        print(f"uploaded {remote_name} ({source.stat().st_size} bytes)", flush=True)
    sftp.close()
finally:
    client.close()
