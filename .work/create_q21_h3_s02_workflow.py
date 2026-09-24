"""Create the inherited-tail H3 workflow for examining the pork."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S02_examine_meat.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "S01_ask_price_end_frame_n174.png"
prompt = """subject_definitions:
<Subject 1> is the same young customer in the black T-shirt, dark trousers and white shoes in <Picture 1>. Preserve his exact animated face, hairstyle, build and outfit.
<Subject 2> is the same middle-aged butcher in the navy shirt and brown apron in <Picture 1>. Preserve his exact animated face and outfit.
<Picture 1> is the actual final frame of the previous ask-price shot. It fixes both people's positions, the pork counter, hanging meat, red lamps, parked scooter, camera and stylized 3D donghua appearance.

summary:
The butcher explains this is premium black-pork meat. Yan Qing leans closer to inspect the meat and gently presses one piece with his fingertip.

retention_analysis:
Continue directly from <Picture 1>. Keep the same fixed two-shot, same counter, same pork display, hanging cuts, red lamps and scooter behind the customer. The same two men remain in their positions and clothing. Preserve the current clear stylized 3D animated rendering, not live-action or photorealistic skin. Meat remains on the tray and hanging rail throughout; do not remove, replace, multiply or rearrange it. The scooter remains parked and its rear rack empty. No extra people, no new props, no cuts, no camera orbit or push-in, no readable text and no scene morphing.

detailed_description:
One continuous locked medium-wide two-shot, 175 frames at 24 fps. At 0.0 seconds continue from the exact supplied frame. The butcher makes a small open-hand gesture toward the pork and explains, "我们家的猪肉可是上好的黑猪肉，和普通猪肉不一样。" Yan Qing studies the meat. Between 2.0 and 4.7 seconds he leans his upper body a little over the customer side of the counter, extends only one hand, and gently presses one piece of pork once with his index fingertip, then withdraws his hand. Keep the arm movement anatomically simple and the pork in place; no cutting, lifting or eating. The butcher stays behind the counter and watches. During the last two seconds Yan Qing gives a thoughtful, mildly impressed look at the cut, as if thinking it does look a little different. His feet stay planted; do not move him toward the scooter. Both faces remain stable and recognizable. Maintain the warm red stall light, cool dawn fill and exact stylized animation look throughout.

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
        node["widgets_values"] = ["qwen21_style_v1/S02_examine_meat/S02_examine_meat_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
