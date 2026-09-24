"""Create the H3 ask-price shot from its Qwen-Image 2.1 camera-cut keyframe."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S01_ask_price.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_S01_ask_price_v2.png"
prompt = """subject_definitions:
<Subject 1> is the young adult customer in the black T-shirt, dark trousers and white shoes in <Picture 1>. Preserve his exact animated face, hair, build and outfit.
<Subject 2> is the middle-aged butcher in the navy shirt and brown apron in <Picture 1>. Preserve his exact animated face and clothes.
<Picture 1> is the approved Qwen-Image 2.1 opening frame. It fixes the medium-wide two-shot, pork-stall layout, hanging meat, red lamps, scooter position, character designs and modern 3D donghua rendering style.

summary:
At the same counter, Yan Qing asks the price. The butcher answers forty-five yuan per jin. Yan Qing is surprised and thinks it is expensive.

retention_analysis:
Keep the exact present-day animated Chinese market scene in <Picture 1>. Maintain its stylized 3D donghua appearance; do not turn it into a live-action-looking or photorealistic scene. Lock the camera and composition. Keep the same two people only, same clothes, same pork, hanging cuts, red lamps, metal counter and parked scooter in the same positions. The scooter remains behind the customer with an empty rear rack. Do not remove or rearrange the meat. No camera orbit, no cut, no reframing, no new people, no duplicate bodies, no readable signs, no captions and no scene morphing.

detailed_description:
One continuous locked medium-wide two-shot, 175 frames at 24 fps. At the start both people hold the exact positions and poses of <Picture 1>. In the first two seconds Yan Qing turns his head slightly toward the butcher and makes one small open-palm gesture toward the pork on the counter as he asks, "老板，这猪肉怎么卖啊？" The butcher answers calmly, "四十五一斤。" From about 3.5 to 5.5 seconds Yan Qing's eyebrows lift, then he gives a restrained doubtful look at the pork and says, "这么贵？" The butcher stays good-natured and gives a small reassuring nod. Both remain on their own sides of the counter; neither walks away or touches the meat yet. Keep movements subtle and readable, with stable faces and hands. Preserve the exact Qwen 2.1 stylized animated character look, warm red stall lights and cool dawn ambience throughout.

overall_soundscape:
Chinese dialogue as written, with quiet market ambience. No music.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 175, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S01_ask_price/S01_ask_price_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
