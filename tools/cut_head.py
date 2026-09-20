#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""【通用工具】把全身设定图的头砍掉 —— 按头身比算裁切线，不盲切。

    python tools/cut_head.py <图1> [图2 ...] [--out 目录] [--ratio 7.5] [--cut 1.30]

## 为什么必须砍头（`pipeline/docs/01_资产规范.md` §1.1）

> 「远景时模型会从那张小而糊的全身图上取脸。把头去掉，模型就只剩一个地方能取脸——脸特写。」

全身图上留着一张简化正脸时，模型**有两个互相冲突的取脸来源**：
全身的脸（正面、寥寥数笔）和特写的脸（3/4、细节丰富）。
结果是远景用全身那张脸、近景用特写那张脸 —— **同一角色在同一集里两张脸**。

## 算法（照 §6.2，不盲切比例）

1. 用**背景色分割**定位人物 bounding box → **头顶 = bbox 上缘**
2. **头高 = 身高 / 头身比**
3. 从头顶往下裁到 **头高 × 1.30**
4. 画布向下重新取景（颈部断面 → 脚底）

§6.2 实测：裁到 `×1.06` 会留下一截光秃秃的脖子（像"被削掉头的脖子柱"）；
裁到 `×1.30` 才是**干净的肩部断面**。

**因为按 bbox 定位而不是按画面比例**，即使模型不遵守"头顶留白"的构图指令也裁得对（§6.2）。

## 为什么有这个文件（而不是"又写了一个 .py"）

同 `tools/draw_plan.py`：`规矩.md` §2 禁的是「为一个**生成任务**新写 .py」。
本文件**不碰 GPU、不提交 prompt**，是确定性图像后处理，
且 `01_资产规范.md` §1.1／§6.2 **明确要求**这道工序。跨项目通用。

## 已知边界

- **地面接触阴影会干扰 bbox 下缘**（§6.3 说生成图普遍带接触阴影）。
  本工具用「与背景色的差异阈值 + 每行非背景像素占比」两道过滤削弱它，
  并**把算出来的数值全部打印出来**供人核对。看不顺眼就用 `--ratio` / `--trim-bottom` 手调。
- 只做**垂直**裁切（颈部以上整体去掉），保持原画布宽度 —— 即 §1.1 的"画布向下重新取景"。
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def bg_color(arr: np.ndarray, patch: int = 12) -> np.ndarray:
    """用四角小块的**中位数**估背景色（比单点稳，能避开角落的暗角）。"""
    h, w, _ = arr.shape
    corners = np.concatenate([
        arr[:patch, :patch].reshape(-1, 3),
        arr[:patch, -patch:].reshape(-1, 3),
        arr[-patch:, :patch].reshape(-1, 3),
        arr[-patch:, -patch:].reshape(-1, 3),
    ])
    return np.median(corners, axis=0)


def person_bbox(arr: np.ndarray, thresh: int, min_frac: float):
    """按背景色分割求人物 bbox。返回 (top, bottom, left, right, row_frac)。

    ★ **背景必须逐行估，不能整幅取一个色。**
    实测第一版用四角中位数当全局背景色，结果 `bbox top=0 bottom=1151`、
    人物宽 767（几乎整张图）—— 分割完全失效。根因是 `01_资产规范.md` §6.3
    早就写明的两件事：生成图**普遍带四角暗角**，且灰底本身是渐变。
    全局背景色对不上画面中央，于是整幅都被判成"人物"。

    改成逐行取左右两端若干列的中位数当该行的背景色，纵向渐变与暗角都能吃掉。
    """
    h, w, _ = arr.shape
    patch = max(4, min(16, w // 32))
    a = arr.astype(np.int16)
    left = a[:, :patch].reshape(h, -1, 3)
    right = a[:, -patch:].reshape(h, -1, 3)
    bg_row = np.median(np.concatenate([left, right], axis=1), axis=1)   # (h, 3)
    diff = np.abs(a - bg_row[:, None, :]).max(axis=2)
    mask = diff > thresh
    row_frac = mask.sum(axis=1) / float(w)
    col_frac = mask.sum(axis=0) / float(h)
    rows = np.where(row_frac >= min_frac)[0]
    cols = np.where(col_frac >= min_frac)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1]), row_frac


def cut_one(src: Path, out_dir: Path, ratio: float, cut: float,
            thresh: int, min_frac: float, trim_bottom: float) -> Path | None:
    im = Image.open(src).convert("RGB")
    arr = np.asarray(im)

    # ★ 阈值自动逐级上探。
    # 实测：默认 28 对背景**横向也有渐变**的图会失效（列全判成人物，left=0/right=W-1），
    # 而同一张图 thresh=45 就正常。与其让人手工试，不如自己往上找第一个 sane 的阈值。
    got, used = None, None
    for t in ([thresh] if thresh not in (28, 0) else [28, 38, 48, 60, 75, 95]):
        g = person_bbox(arr, t, min_frac)
        if g is None:
            continue
        tp, bt, lf, rt, _ = g
        if (bt - tp) <= im.height * 0.98 and (rt - lf) <= im.width * 0.98:
            got, used = g, t
            break
    if got is None:
        print("⚠️  %s：逐级上探到 95 仍分不出人物（bbox 几乎等于整幅）。"
              "这张图不适合自动分割，请手工裁或换一张。" % src.name)
        return None
    if used != thresh:
        print("ℹ️  %s：阈值 %d 会失效，自动升到 %d" % (src.name, thresh, used))
    if got is None:
        print("⚠️  %s：分不出人物与背景，跳过（可调 --thresh）" % src.name)
        return None
    top, bottom, left, right, _ = got
    h = bottom - top
    if trim_bottom > 0:
        bottom = int(bottom - h * trim_bottom)
        h = bottom - top
    head_h = h / ratio
    cut_y = int(round(top + head_h * cut))
    cut_y = max(1, min(cut_y, bottom - 1))

    out = im.crop((0, cut_y, im.width, bottom + 1))
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (src.stem + "_nohead.png")
    out.save(dest)

    print("✅ %s → %s" % (src.name, dest.name))
    print("     原图 %dx%d｜bbox top=%d bottom=%d（高 %d px，人物宽 %d px）"
          % (im.width, im.height, top, bottom, h, right - left))
    print("     头身比 %.2f → 头高 %.1f px → 裁到 头高×%.2f = %.1f px 处"
          % (ratio, head_h, cut, cut_y - top))
    print("     出图 %dx%d" % (out.width, out.height))
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="按头身比砍掉全身设定图的头（资产规范 §1.1/§6.2）")
    ap.add_argument("images", nargs="+", help="输入图（可多个）")
    ap.add_argument("--out", default=None, help="输出目录（默认写到输入图同级的 assets/CHR）")
    ap.add_argument("--ratio", type=float, default=7.5,
                    help="头身比（默认 7.5，写实成年男性常见值；风格化角色可调）")
    ap.add_argument("--cut", type=float, default=1.30,
                    help="裁切倍数（默认 1.30 ＝ 干净肩部断面；1.06 会留脖子柱，见 §6.2）")
    ap.add_argument("--thresh", type=int, default=28, help="与背景色的差异阈值")
    ap.add_argument("--min-frac", type=float, default=0.01,
                    help="每行/列非背景像素的最低占比，用来压掉地面接触阴影")
    ap.add_argument("--trim-bottom", type=float, default=0.0,
                    help="再从 bbox 下缘往上收掉身高的这个比例（治接触阴影，默认 0）")
    args = ap.parse_args()

    made = 0
    for s in args.images:
        src = Path(s)
        out_dir = Path(args.out) if args.out else src.parent.parent / "assets" / "CHR"
        if cut_one(src, out_dir, args.ratio, args.cut,
                   args.thresh, args.min_frac, args.trim_bottom):
            made += 1
    print("\n共处理 %d / %d 张" % (made, len(args.images)))
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
