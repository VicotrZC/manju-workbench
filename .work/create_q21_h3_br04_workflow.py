"""Create the H3 load-the-pork shot from its Qwen 2.1 cut frame."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_BR04_load_pork.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_BR04_load_v2.png"
prompt = """subject_definitions:
<Subject 1> is the young man in the black T-shirt, dark trousers and white sneakers in <Picture 1>. Preserve his exact animated face, hair, build and outfit.
<Subject 2> is the same single blue-gray step-through scooter in <Picture 1>. Preserve its side profile, wheels, seat and empty metal rear rack.
<Picture 1> is the approved Qwen-Image 2.1 opening frame. It fixes the man, the one wrapped pork parcel in his hands, the empty rack, market aisle and stylized 3D donghua look.

summary:
Yan Qing loads the single heavy fifty-jin parcel onto the scooter's rear rack and secures it.

retention_analysis:
Continue from <Picture 1>. There is exactly one wrapped meat parcel in this shot. At the start it is held by Yan Qing and the rear rack is empty. He places that same parcel on the rack, secures it, and leaves it there at the end. Never duplicate the parcel, never put one on the rack before the hands release it, and never make it disappear. Keep the scooter stationary, same side profile, no riding yet. Keep the same modern market, the left pork stall with red lamps and hanging pork, and the same stylized 3D donghua rendering. No extra people, vehicles, meat bags, camera cut, orbit, sign text or scene changes.

detailed_description:
One continuous 107-frame side/rear three-quarter shot at 24 fps. At 0.0 seconds Yan Qing holds the single substantial tied white pork parcel with both hands; the scooter's metal rear rack is visibly empty. From 0.0 to 1.8 seconds he carefully lowers the same parcel onto the center of the rear rack. From 1.8 to 3.6 seconds he uses one simple elastic cargo strap to secure this same one parcel; do not add a second bag or accessory. From 3.6 to 4.46 seconds he releases both hands, checks the parcel once with a light tug, and stands ready to mount. The package remains broad and heavy, consistent with about fifty jin, centered and stable on the rack. The scooter does not roll or change orientation. Preserve his face, outfit, the blue-gray scooter, stall, hanging pork and red lamps. No riding, no extra bag, no change of scene or camera.

overall_soundscape:
Quiet market ambience and a subtle strap rustle. No music.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/BR04_load_pork/BR04_load_pork_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
