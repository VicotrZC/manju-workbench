"""Derive the registered BR01 H3 canvas workflow from the tested project template."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_BR01_market_entry.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_BR01_market_entry_v1_00001_.png"
prompt = """subject_definitions:
<Subject 1> is Yan Qing, the young man in the black T-shirt, dark trousers and white shoes in <Picture 1>. Preserve his hair, body and clothing.
<Subject 2> is the single blue-gray step-through electric scooter in <Picture 1>. Preserve its one rider, wheels, mirrors, saddle and rear rack.
<Subject 3> is the pork seller in the navy work shirt and brown apron behind the stall on frame left.
<Picture 1> fixes the market entrance, aisle, street-side camera axis and left-side pork stall.

summary:
Yan Qing rides through the wet-market entrance toward the visible pork stall on the left.

retention_analysis:
This remains a contemporary pre-dawn Chinese wet market. Keep the same polished 3D animation rendering, entrance columns, overhead roof, rideable aisle and left-side stall. The pork stall's red lamps and hanging meat remain visible as he passes. The rider stays on the same scooter and faces into the market. No axis flip, no jump to the counter, no duplicate protagonist, no change of vehicle, no new sign text and no subtitles.

detailed_description:
One continuous rear three-quarter tracking shot, 107 frames at 24 fps. Begin exactly on the supplied frame with the scooter crossing the threshold. From 0.0 to 1.2 seconds he rolls under the roof at a measured speed; the front wheel crosses the floor transition without a stop or sharp turn. From 1.2 to 3.2 seconds he follows the same central aisle inward. The camera tracks smoothly behind him at the same height and distance. The lit pork stall stays on his left, with red pendant lamps and hanging pork visible; cool blue dawn remains outside behind him and warm stall light fills the interior. From 3.2 to 4.46 seconds he continues deeper along the aisle, still riding and not yet parking. His back, shirt and scooter remain stable, the wheels rotate naturally, and the market columns pass with gentle parallax. Do not add a second rider, do not teleport to the counter, do not turn the scooter around, and do not reframe to a different location. No morphing, no new text, no cut.

overall_soundscape:
No intelligible speech. Quiet early-market room tone and soft electric motor hum.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/BR01_market_entry/BR01_market_entry_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
