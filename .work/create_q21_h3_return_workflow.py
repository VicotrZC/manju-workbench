"""Create the Qwen-Image 2.1-keyframed return-home H3 shot."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S01_return_home.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_S01_return_home_v1.png"
prompt = """subject_definitions:
<Subject 1> is Yan Qing, the same young man in a black T-shirt, dark trousers and white sneakers. Preserve the exact face, hairstyle, body proportions and outfit from <Picture 1>.
<Subject 2> is the same blue-gray step-through scooter with one large tied white pork parcel strapped at the center of its rear rack.
<Picture 1> is the Qwen-Image 2.1 approved opening frame. It fixes the residential street, rider, scooter, single parcel, direction and stylized 3D donghua appearance.

summary:
After buying pork at the market, Yan Qing rides the same scooter with the same single parcel toward home along a quiet predawn street.

retention_analysis:
Continue from <Picture 1> without changing rider identity, outfit, scooter model, road direction or cargo. Exactly one parcel remains strapped to the rear rack for the full shot; it cannot disappear, duplicate, slide or move to a front basket. Travel forward away from the camera on the same residential street, not toward camera. Keep the road, trees, iron fences and lamps stable. No market, no second person, no traffic, no scene cut, no camera orbit or axis flip.

detailed_description:
One continuous 107-frame shot at 24 fps. At 0.0 seconds Yan Qing is already riding away from camera on the quiet road, matching <Picture 1>. He continues at an unhurried steady electric-scooter pace toward the road's vanishing point. The rear three-quarter camera follows smoothly from a modest distance without overtaking him or crossing the road axis. Both wheels roll naturally on the pavement; his shoulders remain relaxed and both hands stay on the handlebars. The single wrapped pork parcel remains firmly strapped on the rear rack and visible throughout. The cool predawn street lighting gradually softens toward early dawn but the environment stays the same. Mature polished Chinese 3D donghua rendering with restrained facial stylization, refined materials and cinematic soft light. No abrupt acceleration, no turning back, no arrival/doorway, no extra cargo, no text, subtitles or music.

overall_soundscape:
Soft electric motor and quiet dawn ambience. No intelligible speech.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S01_return_home/S01_return_home_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
