# 正式生产入口

这里是对话压缩后仍然有效的机器可读生产状态，不依赖聊天记忆。

## 当前状态

`API_H3_V1_*` 已拒绝验收，不得续接。原因见 `../review/API_H3_V1_连续性与来源审计_2026-09-23.md`。

`CHR-02-body` 已按 `production_lock.json` 中的批准记录进入本轮测试。EP02 新增 SCN-03 菜市入口桥段，BR01→BR02→BR03 已逐镜生成并记录实际交接帧；成片及尚存缺陷见 `EP02_SCN03_bridge_QA_2026-09-24.md`。下次生成前仍须把新工作流登记到 `production_lock.json.workflow_registry`，包括确切资产、首帧、上一镜交接帧和成片剪切终点。

工作方式以 `../../../pipeline/docs/09_逐镜反馈与首帧评估.md` 为准：剧本、场景和固定资产提前锁定，连续镜头只逐镜生成、抽帧检查、再制作下一镜首帧；不得预制整条动作链的所有首帧。Qwen-Image-2.1 是待对照的非商用首帧候选，尚未在本项目验证或替换当前出图工具。

## 连续镜

连续动作不重新生成首帧。下一镜直接使用上一镜的实际交接帧，并将上一段精确剪到该帧。帧号是权威，秒数只用于显示：

```text
上一镜 previous_assembly_end_frame_exclusive == 下一镜 handoff_frame_index + 1
```

例如交接图来自第 96 帧，上一镜成片必须在第 97 帧前结束，不能继续保留后面的画面。秒数由 `frame_index / fps` 派生，不能靠手填小数决定剪切点。

## 明确切镜

只有机位真正变化时才允许重新生成首帧。重新生成必须使用项目资产：场景母版或 Blender 对应机位、角色资产、道具母版。参考片仅用于判断节奏、流畅度和镜头语言，不能进入生成模型。

## 执行

```text
python tools/production_guard.py verify-manifest meishi
python tools/production_guard.py verify-workflow meishi <工作流名>
python tools/run.py meishi <工作流名>
```

即使使用 `--skip-gate`，生产来源检查仍会执行。
