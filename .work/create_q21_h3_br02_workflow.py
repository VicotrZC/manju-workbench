"""Derive the registered BR02 inherited-tail H3 canvas workflow."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_BR02_approach_stop.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "BR01_market_entry_end_frame_n106.png"
prompt = """subject_definitions:
<Subject 1> is the young man riding the blue-gray step-through electric scooter in <Picture 1>. Preserve his black shirt, dark trousers, white shoes, body, hair and the exact scooter design.
<Picture 1> is the actual final frame of the previous shot. It fixes the camera, aisle, stall location, screen direction, lighting and the rider's current position.

summary:
He eases off the throttle, turns toward the pork counter on his left and stops beside the stall.

retention_analysis:
Continue directly from <Picture 1> with no cut and no reset. Keep the same rider, scooter and market aisle. The pork stall stays on frame left with its red lamps, white counter and hanging pork visible. Keep its sign text out of focus and unreadable. The scooter's rear rack remains empty. No extra rider, no duplicate vehicle, no change of clothes, no teleport, no reverse movement and no camera orbit.

detailed_description:
One continuous rear three-quarter follow shot, 107 frames at 24 fps. At 0.0 seconds the rider is still rolling forward from the exact supplied frame. During the first second he gently reduces speed and steers left toward the pork counter. From 1.0 to 2.6 seconds the scooter moves the last few meters along the aisle, the front wheel turns slightly toward the stall and the rider looks toward the butcher. From 2.6 to 3.5 seconds he applies the brake and comes to a complete controlled stop parallel to the counter, about one meter away. He stays seated with both hands on the bars; one foot reaches the ground for balance. From 3.5 to 4.46 seconds the scooter remains stationary and the rider looks at the pork stall, ready to dismount in the next shot. Preserve the same light, geometry and mature stylized 3D animation rendering. The parked bike does not disappear and the rear rack stays empty. No camera cut, no framing change, no new sign text, no subtitles and no morphing.

overall_soundscape:
No intelligible speech. Soft electric motor deceleration and quiet market ambience.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/BR02_approach_stop/BR02_approach_stop_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
