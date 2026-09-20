#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本仓库组装成新的干净工作台 `manju-workbench`（一次性，仓库级操作）。

背景（用户 2026-09-20 定）：
  现行仓库累积了**约 268 个项目工作流 JSON、约 220 个项目 SSH 脚本、几代模型的实验脚本**，
  换电脑/换 AI 时噪音太大。所以新开一个干净仓库，只带：
    **规矩 ＋ skill ＋ 通用执行器/工具 ＋ 一部小说**。
  项目内容（资产图、工作流、产物、跑通记录）**一律不带** —— 按新范式重新走。

用法:
    python tools/bootstrap_new_repo.py --target ../manju-workbench          # 干跑，列清单
    python tools/bootstrap_new_repo.py --target ../manju-workbench --apply  # 真组装

⚠️ 只复制，**从不删除源仓库的任何文件**。
"""
from __future__ import annotations

import argparse
import io
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SRC = Path(__file__).resolve().parents[1]

PROJECT = "美食：全市巡摆，馋哭食客"     # 项目 = 小说名
SLUG = "meishi"                          # 命令里用的别名

# ── 带过去：通用层 ──────────────────────────────────────────────────────
COPY_FILES = [
    # 规矩
    "规矩.md",
    "agent.md",
    ".gitignore",
    # 执行器
    "tools/run.py",
    "tools/widget_layout.json",
    # 通用工具（.work/ 90 个里只留这 8 个）
    ".work/run.py",                 # 命令执行器（agent.md §二 强制走它）
    ".work/dl_chunked.py",          # 分块并行下载（agent.md §四 强制）
    ".work/check_before_gpu.py",    # 算力门禁（规矩.md §7）
    ".work/probe_source.py",        # 下载前探测源
    ".work/archive_scripts.py",     # 归档工具
    ".work/comfy_api.py",           # 被 tools/run.py 取代，留作兼容
    ".work/launch_tunnel.py",       # 隧道
    ".work/run_tunnel_daemon.py",   # 隧道守护
    # SSH 通用连接（ssh/ 两百多个里只留这 13 个）
    "ssh/server.txt",
    "ssh/_target.py",
    "ssh/rpy.py",
    "ssh/rc.py",
    "ssh/put.py",
    "ssh/pull_dir.py",
    "ssh/run_remote_py.py",
    "ssh/remote_status.py",
    "ssh/remote_poll.py",
    "ssh/check_any_server.py",
    "ssh/start_comfy.py",
    "ssh/stop_server.py",
    "ssh/check_framing.py",
    # 权威文档（规矩.md §11 那张表点名的）
    "pipeline/docs/01_资产规范.md",
    "pipeline/docs/02_工作规则.md",
    # ⚠️ 03_待办与欠账.md **故意不复制**：它是活文档（当时 60 KB 的旧线欠账），
    #    不是范式文档。新仓库生成一份空的（见 EMPTY_LEDGER），否则一开局就背 60 KB 噪音。
    "pipeline/docs/04_横屏焦距与景别反推表.md",
    "pipeline/docs/05_成本与产能.md",
    "docs/MiniMax_H3_使用与避坑手册.md",
    "docs/生图模型部署与流程.md",
    "docs/中文skill生态调研_2026-09-20.md",
    # H3 官方提示词规范（本地副本，实测与官方逐行相同）
    "h3res/guide_base_en.md",
    "h3res/guide_ref_en.md",
]

COPY_TREES = [
    ("skills", "skills"),                                     # 6 个 skill
    (f"projects/{PROJECT}/source/originals",
     f"projects/{PROJECT}/source/originals"),                 # 50 章小说
]

PROJECT_DIRS = ["story", "script", "storyboard", "prompts",
                "workflows", "review", "assets", "outputs"]

# ── 新写的文件 ──────────────────────────────────────────────────────────
README = """# manju-workbench · 漫剧制作台

用 **AI agent ＋ ComfyUI** 做漫剧 / 短剧的工作台。多项目并行，共用一个执行器。

> **名字里没有模型名，是故意的。** 这个工作台换过三代生图模型
> （SDXL → Qwen-Image-Edit-2509 → Qwen-Image-2512 ＋ Edit-2511），
> 模型会继续换，工作台不该跟着改名。

## 从哪开始

| 想干什么 | 读什么 |
|---|---|
| **接手干活** | [`规矩.md`](规矩.md) → [`projects/<项目>/项目卡.md`](projects) |
| 用户手写的硬约束 | [`agent.md`](agent.md)（**位阶最高**） |
| 跑一个生成任务 | `python tools/run.py <项目slug> <工作流名>` |

**新 AI / 新电脑 / 新聊天**：`git clone` 之后读上面那两个文件就能开工，
不需要旧聊天记录。一切状态都在 git 里。

## 目录

```
规矩.md  agent.md            规矩（规矩.md 是范式，agent.md 位阶最高）
tools/run.py                 【唯一执行器】画布工作流 JSON → 跑 → 下产物
tools/widget_layout.json     widget 布局缓存（可 --refresh-layout 与后端对账）
.work/                       通用工具（命令执行器 / 分块下载 / 门禁 / 隧道 / 探测源）
ssh/                         通用 SSH 连接脚本
skills/                      6 个 agent skill（2026-09-20 从 .zcode/skills/ 搬来；zcode 已卸载）
pipeline/docs/  docs/  h3res/ 权威文档（规矩.md §11 那张表）
projects/<项目>/              一个项目 = 一个文件夹（见 规矩.md §1）
```

## 环境

```bash
pip install -r requirements.txt
```

⚠️ **`ssh_pass.txt` 不在仓库里**（`.gitignore` 已排除，规矩第 2 条）。
换机器要自己放一份在仓库根，`ssh/` 下的脚本都从那里读密码。

## 硬规矩速查

跑 GPU 之前**先过门禁**：

```bash
python .work/check_before_gpu.py --file projects/<项目>/workflows/<工作流>.json
```

有 ERROR 不许开跑。完整 17 条见 [`规矩.md`](规矩.md) §5。
"""

REQUIREMENTS = """# 通用工具的第三方依赖。尽量保持最小。
# 实测：.work/ 下的通用工具里，只有 run.py 需要 paramiko（远程 SSH/SFTP），其余全是标准库。
paramiko>=3.0
"""

# 新仓库的欠账表：**从空开始**。旧仓库那份 60 KB 是另一条产品线的账，不继承。
EMPTY_LEDGER = """# 待办与欠账

> 规矩：**任何承诺当场写进这里**（`规矩.md` §5 硬规矩 16）。
> 只记两件事：① 答应了还没做的；② 发现了但当时没修的问题（带严重度）。
> 做完就删行，别留"已完成"的历史 —— 历史在 `git log` 里。

| # | 事项 | 承诺时间 | 严重度 | 阻塞在谁 |
|---|---|---|---|---|
| — | — | — | — | — |

## 小知识：什么该进这张表

- ✅ 「等云机开了要跑 XX 验证」—— 有明确动作、有阻塞条件
- ✅ 「`.work/xxx.py` 里那处硬编码盘符要改」—— 已知缺陷
- ❌ 想法 / 愿望 / 没有动作的感慨
- ❌ 已完成的（删掉，git 记得）
"""

SOURCE_README = f"""# source/ —— 原著（**只读**）

## 这是什么

**《{PROJECT}》**，共 50 章，在 `originals/`。`index.json` 是章节索引。

**这一层只读。** 改编、删改、合并都发生在 `story/` 和 `script/`，不要动原文
（`规矩.md` §1 的单向依赖：`source → story → script → storyboard → prompts`）。

## 参考片（**不在仓库里**）

复刻用的参考片是 `mmexport1789479809107.mp4`，**没有入库**（视频文件，`.gitignore` 排除）。
它当时放在**旧仓库**的位置：

```
<旧仓库根>/references/videos/mmexport1789479809107.mp4
```

旧仓库：`https://github.com/VicotrZC/MiniMax-H3-Short-Drama`

**为什么留它**：身份基准（`assets/CHR/FILM/`）是从这部片子逐帧裁出来的、**未经任何生成**，
所以身份不可能漂移。而参考图**不可确定性重出**，规矩要求必须单独搬。

**要用时**：从旧仓库或在本地找那份 mp4，放到本项目的 `assets/reference/`（不进 git）。

## 买肉那一场（我们测过的镜头）

`买肉.txt`（在旧仓库 `projects/买肉/source/`）是**第 2 章「新鲜的二师兄」那一场戏的改写节选**，
当时用来测试四镜。它不是独立作品 —— **它属于本项目的一个镜头**。
"""


def project_card() -> str:
    return f"""---
slug: {SLUG}
title: {PROJECT}
---

# {PROJECT} · 项目卡

> **本项目唯一入口。** 范式见根目录 [`规矩.md`](../../规矩.md)。
> 命令里用 `slug`，别敲全名：`python tools/run.py {SLUG} <工作流名>`

## 一句话

把小说《{PROJECT}》（50 章）改编成横屏漫剧。**从零按 `规矩.md` 的范式重新走。**

## 参数（本项目的选择）

| 项 | 值 |
|---|---|
| 画风 | _待定_（旧线是「干净写实」，可沿用可重选） |
| 画风锁定句 | _待定_ |
| 画布 | _待定_（旧线场景卡 1664×928 / 角色卡 1328×1328 / H3 1344×768） |
| 采样 | **8 步 / CFG 1.0**（`规矩.md` §10 的通用口径） |
| 角色资产 | _待定_ |

## 文本层进度（从左到右推进，**不许跳层**）

| 层 | 目录 | 状态 |
|---|---|---|
| 原著 | `source/` | ✅ 50 章已就位 |
| 戏层 | `story/` | ⬜ 未开始（大纲 / 分集 / 人物表） |
| 剧本 | `script/` | ⬜ 未开始 |
| 分镜 | `storyboard/` | ⬜ 未开始 |
| 提示词 | `prompts/` | ⬜ 未开始 |

## 资产清单

| 编号 | 名称 | 状态 | 文件 | 可否确定性重出 |
|---|---|---|---|---|
| — | — | — | — | — |

（图不进 git，这张表进 git）

## 工作流清单

| 文件 | 干什么 | 档位 | 实测耗时 |
|---|---|---|---|
| — | — | — | — |

## 当前进度

- **已完成**：小说原文入库（50 章）
- **进行中**：**空仓库起步** —— 按 `规矩.md` §3 的流程重走
- **下一步**：读 `pipeline/docs/01_资产规范.md` 与 `02_工作规则.md`，
  从「戏层」开始（先定改编范围，不要直接跳分镜）

## 待修

_（空）_

## 本项目的坑

_（空 —— 踩了再写，只写本项目成立的经验）_

## 已知的旧资产在哪（**不在本仓库**）

上一轮在旧仓库 `MiniMax-H3-Short-Drama` 里做过一版（四镜跑通、场景卡、换机位），
产物与工作流**都没有带过来**。如果要用：

| 要什么 | 旧仓库位置 |
|---|---|
| 四镜 H3 工作流 | `workflows/video_h3_s0*_6field_v2.json` |
| 场景卡工作流 | `workflows/scene/SCN_01/02/03b/04` |
| 角色卡工作流 | `workflows/character/BUST_*` |
| 身份基准图 | `assets/CHR/FILM/` |
| 参考片 | `references/videos/mmexport1789479809107.mp4` |

⚠️ 旧版有 4 处已知问题（书名号「」会被画进画面、H3 缺禁字幕句、首帧还是 20 步档、资产未归位）。
**重走时不要再继承这些。**
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="新仓库目录（不存在则创建）")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    dst = Path(args.target).resolve()
    if dst == SRC or SRC in dst.parents:
        print("❌ 目标不能是本仓库内部或它自己")
        return 1

    missing = [f for f in COPY_FILES if not (SRC / f).exists()]
    tree_missing = [s for s, _ in COPY_TREES if not (SRC / s).exists()]

    print(f"源仓库：{SRC}")
    print(f"目标  ：{dst}")
    print(f"\n将复制 {len(COPY_FILES)} 个文件 ＋ {len(COPY_TREES)} 棵目录树：")
    for f in COPY_FILES:
        size = (SRC / f).stat().st_size if (SRC / f).exists() else 0
        flag = "  " if (SRC / f).exists() else "❌"
        print(f"  {flag} {f}  ({size} B)")
    for s, d in COPY_TREES:
        n = len(list((SRC / s).rglob("*"))) if (SRC / s).exists() else 0
        flag = "  " if (SRC / s).exists() else "❌"
        print(f"  {flag} {s}/  →  {d}/   ({n} 个条目)")

    print(f"\n将新建：README.md、requirements.txt、"
          f"projects/{PROJECT}/{{{' '.join(PROJECT_DIRS)}}}、项目卡.md、source/README.md")

    if missing or tree_missing:
        print(f"\n❌ 源仓库缺少：{missing + tree_missing} —— 先修好再来")
        return 1
    if not args.apply:
        print("\n（干跑。确认清单无误后加 --apply。）")
        return 0

    # 复制文件
    for f in COPY_FILES:
        d = dst / f
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / f, d)
    # 复制目录树
    for s, d in COPY_TREES:
        shutil.copytree(SRC / s, dst / d, dirs_exist_ok=True)
    # 项目骨架
    pdir = dst / "projects" / PROJECT
    for sub in PROJECT_DIRS:
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    # 新写的文件
    (dst / "README.md").write_text(README, encoding="utf-8")
    (dst / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (dst / "pipeline" / "docs").mkdir(parents=True, exist_ok=True)
    (dst / "pipeline" / "docs" / "03_待办与欠账.md").write_text(EMPTY_LEDGER,
                                                                encoding="utf-8")
    (pdir / "项目卡.md").write_text(project_card(), encoding="utf-8")
    (pdir / "source" / "README.md").write_text(SOURCE_README, encoding="utf-8")

    # ssh_pass.txt 提醒（**不复制内容**，规矩第 2 条）
    print(f"\n✅ 组装完成 → {dst}")
    print(f"   文件 {sum(1 for _ in dst.rglob('*') if _.is_file())} 个")
    print("\n⚠️ 还要做两件事：")
    print(f"   1. 把 ssh_pass.txt 放到 {dst}（**不进 git**，从旧仓库或你那边取）")
    print("   2. 写一个 source/README.md 里提到的参考片说明已生成，确认无误后：")
    print(f"      cd {dst} && git init && git add -A && git commit -m '初始：规矩+skill+通用工具+小说'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
