"""Create the continuous market-exit H3 shot from BR04's actual selected tail."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_BR05_market_exit.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "BR04_load_pork_end_frame_n106.png"
prompt = """subject_definitions:
<Subject 1> is the same young man in the black T-shirt, dark trousers and white sneakers beside the blue-gray scooter in <Picture 1>. Preserve his exact identity and outfit.
<Subject 2> is the same single blue-gray step-through electric scooter in <Picture 1>, with the same single large white wrapped pork parcel securely strapped to its rear rack.
<Picture 1> is the actual BR04 final frame. Continue from its exact market position, light, camera axis, rider pose and single parcel state.

summary:
Yan Qing mounts the loaded scooter and rides through the market aisle toward the street exit.

retention_analysis:
Continue directly from <Picture 1>. There is one rider, one scooter and exactly one parcel, strapped firmly to the rear rack for the entire shot. Keep the same modern covered market and the left-side pork stall with its hanging pork and warm red lamps visible during the beginning. The scooter must leave the stall area by riding forward along the existing aisle toward the visible market opening. Keep a coherent direction of travel and camera side; do not teleport or cut to the street. No bag duplication, no parcel loss, no basket, no new people in foreground, no signage text, no camera orbit or axis flip.

detailed_description:
One continuous 107-frame shot at 24 fps. At 0.0 seconds Yan Qing is standing beside the stationary scooter, having just checked its one strapped parcel. From 0.0 to 1.2 seconds he mounts naturally from the near side, settles on the seat and places both hands on the handlebars. From 1.2 to 1.8 seconds he starts the scooter and pushes off smoothly. From 1.8 to 4.46 seconds he rides forward down the same market aisle toward the daylight street exit, passing the same pork stall on the left. Use a gentle rear three-quarter follow camera that tracks with him without overtaking or changing sides. Keep the exact single parcel firmly on the rear rack, no bouncing or sliding. Preserve scooter design, rider outfit, market columns and roof, hanging pork and red lamps through the departure. Mature polished Chinese 3D donghua rendering. No cut, no scene change before reaching the threshold, no extra vehicle, no second package, no readable text, no dialogue subtitles.

overall_soundscape:
Quiet market ambience, soft scooter start and smooth electric motor roll. No intelligible speech.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 107, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/BR05_market_exit/BR05_market_exit_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
