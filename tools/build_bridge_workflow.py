"""Derive one bridge-shot H3 workflow from the approved S00 template."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("image")
    parser.add_argument("prompt_file", type=Path)
    parser.add_argument("--frames", type=int, default=124)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1] / "projects" / "美食：全市巡摆，馋哭食客"
    source = project / "workflows" / "V2_CODEX_EP02SC02_S00_outbound_v2_h3.json"
    target = project / "workflows" / f"{args.name}.json"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite: {target}")
    workflow = json.loads(source.read_text(encoding="utf-8-sig"))
    for node in workflow["nodes"]:
        if node["id"] == 6:
            node["widgets_values"][0] = args.image
        elif node["id"] == 7:
            node["widgets_values"][0] = args.prompt_file.read_text(encoding="utf-8")
            node["widgets_values"][3] = args.frames
        elif node["id"] == 16:
            node["widgets_values"][0] = f"meishi/{args.name}"
    target.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
