"""Assemble the reviewed Qwen-Image 2.1 + H3 shots into a silent visual cut."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "美食：全市巡摆，馋哭食客"
BASE = PROJECT / "outputs" / "QWEN21_STYLE_V1"
FFMPEG = ROOT / "tools" / "ffmpeg.exe"
if not FFMPEG.is_file():
    FFMPEG = ROOT.parent / "minimax-h3-cloud" / "tools" / "ffmpeg.exe"
OUTPUT = BASE / "QWEN21_BUY_MEAT_VISUAL_V1.mp4"

SHOTS = [
    ("S00_outbound", "S00_outbound_h3_00001_.mp4"),
    ("BR01_market_entry", "BR01_market_entry_h3_00001_.mp4"),
    ("BR02_approach_stop", "BR02_approach_stop_h3_00001_.mp4"),
    ("BR03_dismount", "BR03_dismount_h3_00001_.mp4"),
    ("S01_ask_price", "S01_ask_price_h3_00001_.mp4"),
    ("S02_examine_meat", "S02_examine_meat_h3_00001_.mp4"),
    ("S03_phone_evidence", "S03_phone_evidence_h3_00001_.mp4"),
    ("S04_order_pack_start", "S04_order_pack_start_h3_00001_.mp4"),
    ("S05_package_handoff", "S05_package_handoff_h3_00001_.mp4"),
    ("BR04_load_pork", "BR04_load_pork_h3_00001_.mp4"),
    ("BR05_market_exit", "BR05_market_exit_h3_00001_.mp4"),
    ("S01_return_home", "S01_return_home_h3_00001_.mp4"),
]
videos = [BASE / folder / filename for folder, filename in SHOTS]
missing = [path for path in videos if not path.is_file()]
if missing:
    raise FileNotFoundError("Missing shot(s):\n" + "\n".join(map(str, missing)))
if not FFMPEG.is_file():
    raise FileNotFoundError(FFMPEG)

args = [str(FFMPEG), "-y"]
for video in videos:
    args += ["-i", str(video)]
labels = "".join(f"[{index}:v:0]" for index in range(len(videos)))
args += [
    "-filter_complex", f"{labels}concat=n={len(videos)}:v=1:a=0[v]",
    "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium",
    "-crf", "18", "-pix_fmt", "yuv420p", "-r", "24", "-movflags", "+faststart",
    str(OUTPUT),
]
subprocess.run(args, check=True)
print(OUTPUT)
