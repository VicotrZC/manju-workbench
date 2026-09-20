#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 .work/ 下的一次性脚本归档到 archive/work_scripts/（**只移动，不删除**）。

判据：**是否被仓库其他地方引用**。被引用的留下；没人引用的才归档。
（`agent.md` 强制要求的工具如 `.work/run.py`、`.work/dl_chunked.py` 在白名单里，永远保留。）

为什么不能一把梭全归档：搬走一个还在被别的脚本 import 或文档点名的文件 = 直接把仓库搞坏。

用法:
    python .work/archive_scripts.py              # 干跑，只打印分类
    python .work/archive_scripts.py --apply      # 真归档（git mv；未跟踪的用 mv）
    python .work/archive_scripts.py --apply --include-json   # 连 .json/.txt 一起归档
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work"
ARCHIVE = ROOT / "archive" / "work_scripts"

# 永远保留（工具链骨架 + agent.md 强制要求的）
KEEP = {
    "run.py",                  # agent.md §二：命令一律走它
    "dl_chunked.py",           # agent.md §四：分块并行下载
    "check_before_gpu.py",     # 规矩.md §7：门禁
    "archive_scripts.py",      # 本文件
    # comfy_api.py 已于 2026-09-20 删除（被 tools/run.py 取代，且写死 E 盘），不再保留
    "launch_tunnel.py",        # 隧道
    "run_tunnel_daemon.py",    # 隧道
    "tunnel_comfyui.py",       # 隧道本体（守护依赖它）
}

SCAN_EXT = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".ps1"}
SKIP_DIRS = {".git", "venv", "node_modules", "__pycache__", "archive",
             ".cache", "site-packages"}


def repo_text_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SCAN_EXT:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def references(name: str, files: list[Path], self_path: Path,
               outside_only: bool = False) -> list[str]:
    """返回引用了 name 的文件（相对路径），排除它自己。

    outside_only=True 时**只认 `.work/` 之外的引用** —— 因为 `.work` 内部
    一群一次性脚本互相 import 会形成"死簇"，整簇都被判成"还在用"。
    """
    pat = re.compile(re.escape(name))
    hits = []
    for f in files:
        if f == self_path:
            continue
        if outside_only and WORK in f.parents:
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pat.search(txt):
            hits.append(str(f.relative_to(ROOT)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-json", action="store_true",
                    help="连 .json/.txt 也一起归档（默认只归档 .py）")
    args = ap.parse_args()

    exts = {".py"} | ({".json", ".txt"} if args.include_json else set())
    targets = sorted(p for p in WORK.glob("*") if p.is_file() and p.suffix in exts)
    if not targets:
        print("没有可归档的文件")
        return 0

    files = repo_text_files()
    by_name = {p.name: p for p in targets}

    # ── 种子：白名单 ∪ 被 .work 之外引用的 ──────────────────────────
    seed: dict[str, list[str]] = {}
    for p in targets:
        if p.name in KEEP:
            seed[p.name] = ["（白名单）"]
            continue
        out_refs = references(p.name, files, p, outside_only=True)
        if out_refs:
            seed[p.name] = out_refs

    # ── 闭包：种子内部 import 的 .work 脚本也要留 ────────────────────
    keep = dict(seed)
    frontier = list(seed)
    while frontier:
        name = frontier.pop()
        p = by_name.get(name)
        if not p:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for other in targets:
            if other.name in keep or other.name == name:
                continue
            # 只认显式 import / 同目录调用（形如 import X 或 from X import）
            stem = other.stem
            if re.search(rf"\b(import|from)\s+{re.escape(stem)}\b", txt):
                keep[other.name] = [f"被保留的 {name} import"]
                frontier.append(other.name)

    arch = [p for p in targets if p.name not in keep]

    print(f"扫描 .work/ 下 {len(targets)} 个文件（{'/'.join(sorted(exts))}）\n")
    print(f"=== 保留：{len(keep)} 个 ===")
    for name in sorted(keep):
        refs = keep[name]
        shown = "、".join(refs[:2]) + ("…" if len(refs) > 2 else "")
        print(f"  {name:<44} ← {shown}")
    print(f"\n=== 归档：{len(arch)} 个（.work 之外无人引用）===")
    for p in arch:
        print(f"  {p.name}")

    if not args.apply:
        print(f"\n（干跑。确认无误后加 --apply —— 会 git mv 到 "
              f"{ARCHIVE.relative_to(ROOT)}/，**不删任何文件**）")
        return 0

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    moved = untracked = 0
    for p in arch:
        dest = ARCHIVE / p.name
        rel = str(p.relative_to(ROOT))
        r = subprocess.run(["git", "mv", rel, str(dest.relative_to(ROOT))],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            moved += 1
        else:
            p.rename(dest)          # 未跟踪的文件 git mv 会失败，直接移动
            untracked += 1
    print(f"\n✅ 已归档 {moved} 个（git mv）+ {untracked} 个（未跟踪，直接移动）→ {ARCHIVE}")
    print("   一个都没删。要找还能找到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
