#!/usr/bin/env python
"""Project production-source and continuity guard.

This gate is deliberately independent from conversational memory and from the
older audit seal.  It verifies the machine-readable production lock before a
video workflow can be submitted.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"
VIDEO_NODE_TYPES = {"MiniMaxH3ReferenceToVideo", "SaveVideo", "CreateVideo"}

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def project_dir(name: str) -> Path:
    direct = PROJECTS / name
    if direct.is_dir():
        return direct
    for path in PROJECTS.iterdir():
        card = path / "项目卡.md"
        if card.exists() and f"slug: {name}" in card.read_text(encoding="utf-8-sig"):
            return path
    raise SystemExit(f"找不到项目：{name}")


def load_lock(project: Path) -> tuple[Path, dict]:
    path = project / "production" / "production_lock.json"
    if not path.exists():
        return path, {}
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def norm(value: str) -> str:
    return value.replace("\\", "/").lower()


def forbidden(value: str, lock: dict) -> str | None:
    target = norm(value)
    for item in lock.get("forbidden_generation_sources", []):
        if norm(item) in target:
            return item
    return None


def workflow_load_images(workflow: dict) -> list[str]:
    result = []
    for node in workflow.get("nodes", []):
        if node.get("type") == "LoadImage":
            values = node.get("widgets_values") or []
            if values and isinstance(values[0], str):
                result.append(values[0])
    return result


def is_video_workflow(workflow: dict) -> bool:
    return any(node.get("type") in VIDEO_NODE_TYPES for node in workflow.get("nodes", []))


def verify_manifest(project: Path, lock: dict) -> list[str]:
    errors: list[str] = []
    if not lock:
        return errors
    if lock.get("schema_version") != 1:
        errors.append("production_lock.json schema_version 必须为 1")
    assets = lock.get("approved_assets") or {}
    for asset_id, asset in assets.items():
        rel = asset.get("path")
        if not rel:
            errors.append(f"资产 {asset_id} 缺 path")
            continue
        hit = forbidden(rel, lock)
        if hit:
            errors.append(f"资产 {asset_id} 命中禁止来源 {hit}: {rel}")
        if not (project / rel).exists():
            errors.append(f"资产 {asset_id} 文件不存在: {rel}")

    registry = lock.get("workflow_registry") or {}
    for name, entry in registry.items():
        path = project / "workflows" / f"{name}.json"
        if not path.exists():
            errors.append(f"登记工作流不存在: {name}")
        for source in entry.get("source_paths", []):
            hit = forbidden(source, lock)
            if hit:
                errors.append(f"工作流 {name} 来源命中禁止项 {hit}: {source}")
        for asset_id in entry.get("asset_ids", []):
            asset = assets.get(asset_id)
            if asset is None:
                errors.append(f"工作流 {name} 使用未登记资产: {asset_id}")
            elif asset.get("status") != "approved":
                errors.append(
                    f"工作流 {name} 使用未批准资产 {asset_id}: {asset.get('status')}"
                )
        if entry.get("first_frame_mode") == "inherited_tail":
            handoff = entry.get("handoff") or {}
            required = (
                "previous_workflow", "previous_video", "handoff_frame",
                "fps", "handoff_frame_index",
                "previous_assembly_end_frame_exclusive",
                "handoff_time_s", "previous_assembly_end_s",
            )
            for key in required:
                if key not in handoff:
                    errors.append(f"工作流 {name} 的 handoff 缺字段: {key}")
            frame_keys = (
                "handoff_frame_index", "previous_assembly_end_frame_exclusive",
            )
            if all(key in handoff for key in frame_keys):
                if int(handoff["previous_assembly_end_frame_exclusive"]) != (
                    int(handoff["handoff_frame_index"]) + 1
                ):
                    errors.append(
                        f"工作流 {name} 交接帧 {handoff['handoff_frame_index']} 与上一镜"
                        f"剪切终点 {handoff['previous_assembly_end_frame_exclusive']} 不连续"
                    )
            time_keys = ("fps", "handoff_frame_index", "handoff_time_s")
            if all(key in handoff for key in time_keys):
                derived = int(handoff["handoff_frame_index"]) / float(handoff["fps"])
                if abs(derived - float(handoff["handoff_time_s"])) > 0.001:
                    errors.append(
                        f"工作流 {name} handoff_time_s 不是由帧号/fps 派生："
                        f"登记 {handoff['handoff_time_s']}，应为 {derived:.6f}"
                    )
    return errors


def verify_workflow(project: Path, lock: dict, name: str) -> list[str]:
    errors = verify_manifest(project, lock)
    path = project / "workflows" / f"{name}.json"
    if not path.exists():
        return errors + [f"工作流不存在: {path}"]
    workflow = json.loads(path.read_text(encoding="utf-8-sig"))
    if not is_video_workflow(workflow):
        return errors

    registry = lock.get("workflow_registry") or {}
    entry = registry.get(name)
    if lock.get("enforce_video_workflows") and entry is None:
        return errors + [
            f"视频工作流 {name} 未登记在 production_lock.json.workflow_registry；拒绝提交"
        ]
    if entry is None:
        return errors

    actual = {Path(x).name for x in workflow_load_images(workflow)}
    expected = {Path(x).name for x in entry.get("load_images", [])}
    if actual != expected:
        errors.append(
            f"工作流 {name} 的 LoadImage 与生产锁不一致；实际 {sorted(actual)}，"
            f"登记 {sorted(expected)}"
        )
    for image in actual:
        hit = forbidden(image, lock)
        if hit:
            errors.append(f"工作流 {name} 的 LoadImage 命中禁止来源 {hit}: {image}")
    return errors


def report(errors: list[str]) -> int:
    if errors:
        print("⛔ 生产来源/连续性门禁不通过：")
        for error in errors:
            print(f"   - {error}")
        return 1
    print("✅ 生产来源/连续性门禁通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("verify-manifest")
    manifest.add_argument("project")
    workflow = sub.add_parser("verify-workflow")
    workflow.add_argument("project")
    workflow.add_argument("workflow")
    args = parser.parse_args()

    project = project_dir(args.project)
    _, lock = load_lock(project)
    if not lock:
        print("（项目没有 production/production_lock.json，生产门禁未启用）")
        return 0
    if args.command == "verify-manifest":
        return report(verify_manifest(project, lock))
    return report(verify_workflow(project, lock, args.workflow))


if __name__ == "__main__":
    sys.exit(main())
