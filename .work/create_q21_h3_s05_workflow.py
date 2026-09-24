"""Create the inherited-tail H3 package handoff shot."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S05_package_handoff.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "S04_order_pack_start_end_frame_n174.png"
prompt = """subject_definitions:
<Subject 1> is the same young customer in the black T-shirt, dark trousers and white shoes in <Picture 1>. Preserve his exact animated face, identity and clothes.
<Subject 2> is the same middle-aged butcher in the navy work shirt and brown apron in <Picture 1>. Preserve his exact face and clothes.
<Picture 1> is the actual final frame of the order shot. It fixes the single wrapped pork parcel on the scale, the counter, meat display, two people, parked scooter and current stylized 3D donghua look.

summary:
The butcher finishes securing the wrapped pork parcel and hands it to Yan Qing, who receives it with both hands.

retention_analysis:
Continue directly from <Picture 1>, keeping the fixed medium counter two-shot, same characters, same stall, same hanging pork, red lamps and parked scooter. The parcel on the scale is the same single parcel throughout; do not duplicate it, enlarge it, replace it with raw meat or make it disappear. Preserve the clean stylized 3D animation look. The scooter remains parked and its rear rack empty. No camera movement, no cut, no extra people, no new objects and no scene morphing.

detailed_description:
One continuous 107-frame shot at 24 fps. At the first frame the same pork parcel rests on the scale. The butcher folds and secures the final paper flap with two small hand movements, then lifts the parcel and extends it across the counter. Yan Qing reaches forward with both hands and takes the same parcel. The transfer is slow and clear; their hands do not merge or swap. The butcher gives a friendly smile and says, "小伙子，以后多光顾啊！" Yan Qing looks grateful and holds the parcel close to his torso. Keep the parcel visible in the customer's hands at the end; do not load it onto the scooter in this shot. Preserve faces, clothing, scale, meat and lighting. No walking away, no payment, no text, no camera shake.

overall_soundscape:
Chinese dialogue as written with quiet market ambience. No music.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S05_package_handoff/S05_package_handoff_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
