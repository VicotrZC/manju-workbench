"""Derive the registered BR03 inherited-tail H3 canvas workflow."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_BR03_dismount.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "BR02_approach_stop_end_frame_n106.png"
prompt = """subject_definitions:
<Subject 1> is the young man in the black T-shirt, dark trousers and white shoes, seated on the blue-gray electric scooter in <Picture 1>. Preserve his identity and outfit.
<Subject 2> is the same single step-through scooter in <Picture 1>. Keep its rear wheel, seat and rack visible and unchanged.
<Picture 1> fixes the actual parked position beside the left pork stall, the counter side, lighting and camera axis.

summary:
Yan Qing switches off the scooter, dismounts to its left and takes one short step toward the pork counter.

retention_analysis:
Continue exactly from the supplied final frame. The scooter is already stopped beside the same stall; keep it parked there with its rear rack empty. Keep the hanging pork and red lamps visible on the left. Preserve one protagonist, the same clothes and scooter, and the same market light. The camera may ease backward slightly to reveal his legs and the whole dismount, then hold still. Do not cut, orbit, flip the axis, move the scooter, add a second rider, change the stall, or add readable text.

detailed_description:
One continuous shot, 107 frames at 24 fps. At 0.0 seconds Yan Qing is stopped and seated exactly as in <Picture 1>. From 0.0 to 1.1 seconds he steadies the scooter with his left foot while the camera makes a gentle small dolly backward, revealing more of the scooter and floor without changing its viewing side. From 1.1 to 1.8 seconds he switches off the motor and lowers the kickstand; the scooter stays completely still. From 1.8 to 3.1 seconds he swings his right leg over the rear seat and steps down to the left side, ending upright beside the same parked scooter. From 3.1 to 4.46 seconds he turns his shoulders toward the butcher and takes one short step toward the counter. His body moves naturally, both feet remain on the floor after dismounting, and the bike stays planted on its stand. Keep the same stall geometry, meat, red lamps and cool dawn fill throughout. Stable mature stylized 3D animation. No teleporting, no duplicated limbs, no rider remaining on the seat after dismount, no camera cut, no subtitles and no morphing.

overall_soundscape:
No intelligible speech. Soft switch click, kickstand tap and quiet market ambience.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/BR03_dismount/BR03_dismount_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
