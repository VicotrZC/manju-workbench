"""Derive the registered S00 H3 canvas workflow from the tested project template."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S00_outbound.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_S00_outbound_v1_00001_.png"
prompt = """subject_definitions:
<Subject 1> is Yan Qing, the young Chinese man in the black T-shirt, dark trousers and white shoes shown in <Picture 1>. Preserve his body, hair, clothing and animation identity.
<Subject 2> is the blue-gray step-through electric scooter shown in <Picture 1>. Preserve its wheels, frame, single seat, mirrors and rear rack.
<Picture 1> fixes the modern residential street, rear three-quarter camera, road axis, lighting and direction of travel.

summary:
At about four in the morning, Yan Qing rides alone along the quiet neighborhood road toward the wet market.

retention_analysis:
Maintain the polished mature Chinese 3D animated-series rendering of the opening frame. Keep exactly one rider and one scooter. The road recedes to the same vanishing point; the trees, streetlights, iron fences and scooter shelter stay on their original sides. The rear rack stays empty because he has not bought the pork yet. No stall, no vendors, no extra people, no traffic, no wardrobe changes, no camera cut and no axis flip.

detailed_description:
One continuous rear three-quarter tracking shot lasting eight seconds. The shot begins exactly on the supplied frame, already in motion. From 0.0 to 2.0 seconds the scooter rolls steadily forward; both wheels turn in the correct direction and the rider keeps both hands on the handlebars. From 2.0 to 5.5 seconds the camera follows smoothly at the same height and distance, with gentle parallax in the trees, lamps and fences. His elbows and shoulders absorb small road vibrations; his head stays aimed toward the road. From 5.5 to 8.0 seconds he continues farther toward the same vanishing point at the same natural speed. Keep the rear view and the same camera axis throughout. The dawn sky remains dark blue, with only subtle reflections on the pavement. This is a restrained, high-quality 3D animated drama frame with natural human proportions and consistent materials. No sudden acceleration, no turn, no stop, no extra cargo, no new objects, no morphing, no text or subtitles.

overall_soundscape:
No intelligible speech. Quiet distant early-morning ambience and a soft electric motor hum.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 192, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S00_outbound/S00_outbound_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
