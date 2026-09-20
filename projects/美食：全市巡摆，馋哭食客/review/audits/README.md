# 本项目的审计记录

> 判据与检查码表：`pipeline/docs/06_审计闸门.md`。规矩入口：`规矩.md` §7。
> 命令一律 `python tools/pipeline_audit.py <cmd> meishi ...`

## 这里的文件是什么

| 文件 | 谁写 | 作用 |
|---|---|---|
| `<工作流>.verdict.json` | **子 agent / 人** | 审计判定（写进 git，可复盘） |
| `<工作流>.audit.json` | `pipeline_audit.py seal` | **封条**：钉着被审文件的 sha256 |
| `postflight.verdict.json` | 子 agent | 项目做完之后的**流程**审计判定 |
| `<工作流>.packet.json`（在 `.work/audit/packets/`） | `preflight` | 审计包：完整提示词 ＋ 机械检查结果 ＋ 该镜认领的节拍 |

## 规矩

1. **封条绑 sha256。改了提示词 / 戏 / 镜头表 / `audit_rules.json` → 封条立即过期 → `run.py` 拒绝提交。**
   过期了就跑 `preflight` → 子 agent → `seal`，不要绕过。
2. **机械 ERROR 不许被判 pass 盖过去。** `seal` 会数 ERROR；判定写 `pass` 却留着未处理的 ERROR，直接拒绝封存。
   要么修，要么在 `waivers` 里**逐条给理由**。
3. **子 agent 报"通过" ≠ 内容合格**（`规矩.md` §5.C 第 12 条）。
   它只回答"上游写的有没有落到提示词里"；**好不好看、像不像、表演能不能接受，只有用户能判**。
