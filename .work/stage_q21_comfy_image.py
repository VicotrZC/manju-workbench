"""Upload one local Qwen/H3 handoff frame to the matching remote ComfyUI input."""
import argparse
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "美食：全市巡摆，馋哭食客"
OUTPUTS = (PROJECT / "outputs").resolve()
REMOTE_INPUTS = {
    "h3": "/root/autodl-tmp/ComfyUI/input",
    "qwen21": "/root/autodl-tmp/ComfyUI-qwen21/input",
}
sys.path.insert(0, str(ROOT / "ssh"))
from _target import password, target  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("target", choices=REMOTE_INPUTS)
parser.add_argument("image", help="Project-relative image path under outputs/")
args = parser.parse_args()
source = (PROJECT / args.image).resolve()
if not source.is_relative_to(OUTPUTS) or not source.is_file():
    raise SystemExit("image must be an existing file beneath the project outputs directory")

host, port = target()
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port=port, username="root", password=password(), timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = client.open_sftp()
    destination = f"{REMOTE_INPUTS[args.target]}/{source.name}"
    sftp.put(str(source), destination)
    sftp.close()
finally:
    client.close()
print(f"staged {source.name} to {args.target} ComfyUI input ({source.stat().st_size} bytes)")
