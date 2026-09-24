"""Create the H3 phone-evidence shot from its Qwen 2.1 camera-cut keyframe."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = root / "projects" / "美食：全市巡摆，馋哭食客"
source = project / "workflows" / "V3_H3_S01_arrive.json"
target = project / "workflows" / "QWEN21_V1_H3_S03_phone_evidence.json"
if target.exists():
    raise SystemExit(f"refusing to overwrite {target}")

workflow = json.loads(source.read_text(encoding="utf-8-sig"))
firstframe = "Q21_KEYFRAME_S03_phone_v1.png"
prompt = """subject_definitions:
<Subject 1> is the young male customer at frame left in <Picture 1>. Preserve his exact stylized animated face, black hair, black T-shirt and identity.
<Subject 2> is the middle-aged butcher at frame right in <Picture 1>. Preserve his exact stylized animated face, navy work shirt and brown apron.
<Picture 1> is the approved Qwen-Image 2.1 close two-shot. It fixes both identities, screen directions, phone position and its video image, market lights, hanging pork and 3D donghua art direction.

summary:
Yan Qing asks whether the pork was butchered this morning. The butcher earnestly shows a phone video of lively pigs riding on a truck into a processing-facility gate. Yan Qing is startled, then slowly smiles.

retention_analysis:
Continue from <Picture 1> with the same two men, one black smartphone, exact phone-screen image, same stall and same medium-close framing. Keep the screen pointed toward the customer and camera and large enough to see. Preserve the illustrated 3D donghua style; never convert the faces to live action. The smartphone screen content is a benign farm-truck video and stays within the phone screen. Keep a few red lamps and hanging pork softly visible behind them. No extra people in the foreground, no new props, no second phone, no cut, no zoom, no orbit, no mirroring, no text overlays, no screen swap and no scene morphing.

detailed_description:
One continuous 294-frame shot at 24 fps. From 0.0 to 2.5 seconds Yan Qing glances from the butcher to the pork and asks, "老板，你这猪肉是早上现杀的吗？" The butcher answers sincerely, "你放心，绝对新鲜，刚从屠宰场拉回来，不信你看看。" From about 2.5 to 5.0 seconds the butcher makes one small controlled wrist turn to angle the phone more directly toward Yan Qing; he does not thrust it into the man's face. The phone display continues showing a short video: several lively healthy pigs ride in the back of a farm truck as it slowly passes through a clean rural processing-facility gate. No distress or graphic imagery. From 5.0 to 8.5 seconds Yan Qing leans a little closer and studies the screen. From 8.5 to 10.0 seconds he pauses, eyes widening slightly as he understands what he is seeing. From 10.0 to 12.25 seconds he slowly breaks into a small amused smile and says, "嘿，是挺新鲜。" The butcher stays completely earnest and matter-of-fact, with a mild reassuring expression. Keep both faces stable and readable; preserve the same phone and its screen image for the entire shot. Subtle gestures only; no broad acting, no cuts, no camera movement.

overall_soundscape:
The Chinese dialogue above with quiet market ambience. No music and no added comic sound effects.

non_diegetic_music:
none"""

for node in workflow["nodes"]:
    if node.get("type") == "LoadImage":
        node["widgets_values"] = [firstframe, "image"]
    elif node.get("type") == "MiniMaxH3ReferenceToVideo":
        node["widgets_values"] = [prompt, 1376, 768, 294, "match"]
    elif node.get("type") == "SaveVideo":
        node["widgets_values"] = ["qwen21_style_v1/S03_phone_evidence/S03_phone_evidence_h3", "auto", "auto"]

target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
