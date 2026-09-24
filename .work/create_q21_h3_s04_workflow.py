"""Create the H3 order shot from its Qwen-Image 2.1 camera-cut keyframe."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S04_order_pack_start.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_S04_order_v1.png"
prompt = """subject_definitions:
<Subject 1> is the same young male customer in the black T-shirt, dark trousers and white shoes in <Picture 1>. Preserve his animated face, identity and outfit.
<Subject 2> is the same middle-aged butcher in the navy shirt and brown apron in <Picture 1>. Preserve his animated face and outfit.
<Picture 1> is the approved Qwen-Image 2.1 order-shot opening frame. It fixes the two-shot, counter, meat display, parked scooter, character designs and stylized 3D donghua appearance.

summary:
Yan Qing orders fifty jin of pork. The butcher agrees happily and begins preparing the order.

retention_analysis:
Continue from <Picture 1> with the same two people, same sides of the counter, same modern pork stall and same stylized animated look. Keep the blue-gray scooter parked behind the customer, unchanged, its rear rack still empty. Keep the hanging pork, red lamps and pork trays visible and consistent. The butcher's phone is put away and stays out of view. No extra people, no camera movement, no cut, no scene changes, no text overlays, no duplication of people, meat or scooter.

detailed_description:
One continuous locked medium two-shot, 175 frames at 24 fps. Yan Qing looks directly at the butcher and says clearly, "老板，给我来五十斤猪肉。" He makes one small decisive open-palm gesture toward the meat. The butcher brightens, nods once and replies, "好嘞。" He turns only slightly toward the scale, reaches for one clean sheet of wrapping paper and starts moving a single portion of pork toward the scale. Do not finish packing the whole order in this shot; stop while he is beginning the preparation so the next shot can show the complete wrapping and handoff. Yan Qing waits at the customer side of the counter. Keep gestures modest and faces stable; keep the same premium Chinese 3D donghua rendering and warm market light. No walking away, no payment exchange, no new prop other than one piece of clean wrapping paper.

overall_soundscape:
Chinese dialogue as written with quiet market ambience. No music.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 175, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S04_order_pack_start/S04_order_pack_start_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
