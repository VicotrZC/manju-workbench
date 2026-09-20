#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""【通用工具】场景平面调度图 / 机位调度图 —— 程序化绘制。

    python tools/draw_plan.py <场景规格.json> [--out 目录] [--mode plan|cams|both]

## 为什么有这个文件（而不是"又写了一个 .py"）

`规矩.md` §2 禁止的是「**为一个生成任务**新写一个 .py」。本文件不是生成任务：

- 它**不碰 GPU、不提交任何 prompt**，只做确定性绘图；
- `pipeline/docs/01_资产规范.md` §2.1 **明确要求**平面调度图必须
  「**程序化绘制**」而不是生成 —— 因为图上有**精确的米数与角度**，
  生成模型画不出可信的尺寸；
- 它**跨项目通用**：输入是一份场景规格 JSON，换项目只换数据不换代码。

> ⚠️ 放置说明：`01_资产规范.md` §2 与 `04` §八 都把这张图指向
> `pipeline/storyboard/draw_plan.py`。**但那个文件在新旧两个仓库里都不存在**
> （实测：`pipeline/storyboard/` 目录本身就没有）。且 `规矩.md` §10 说明
> `pipeline/` 是**另一条产品线**（Blender 预演／《我的系统有编制》），
> 「范式共用，具体参数/路径不通用」。所以本工具落在 **`tools/`**，
> 与 `run.py` 并列，作为通用工具。

## 输入规格（JSON）字段

| 键 | 必填 | 说明 |
|---|---|---|
| `scene_id` / `name` | ✅ | 场景编号与名字 |
| `extent` | ✅ | `{"x":[x0,x1], "y":[y0,y1]}` 绘图范围（米） |
| `grid_m` | | 网格间距，默认 1.0（§2.1 第 2 条：一格 = 1 米） |
| `solids` | ✅ | 场地实体块：`{id,label,x0,x1,y0,y1,fill?}` —— **画成有尺寸的矩形，不能只写字**（§2.1 第 1 条） |
| `anchors` | | 锚点物编号：`{id,label,x,y}`（§2.1 第 7 条） |
| `axis_line` | | 动作轴线：`{x0,y0,x1,y1,label}`（§2.1 第 4 条） |
| `ab_line` | ✅ | **A/B 侧分界线**：`{x0,y0,x1,y1,label}`，**必须贯穿全场并延伸到框外**（§2.1 第 5 条） |
| `actors` | | 站位点：`{id,label,x,y,facing_deg}`（0°=+x 东，90°=+y 北） |
| `cameras` | | 机位：`{id,label,x,y,yaw_deg,lens_mm,dist_m}` —— 画**朝向箭头 ＋ 视锥扇形**（§2.1 第 6 条） |
| `north_deg` | | 图纸上"北"的朝向，默认 90（正上方） |

## 光学公式（与 `04_横屏焦距与景别反推表.md` 一致，**不另立一套**）

`sensor_fit='AUTO'` 贴长边 → 横屏起作用的始终是 `eff_h = 36.0 mm`，**与画幅宽高无关**。
（本项目画幅 1376×768，`eff_v = 36×768/1376 = 20.0930`；画布改了 `eff_h` 也不变。）

```
水平 FOV      fov_h_deg(L)          = 2·atan(eff_h / (2L))
可见宽度      visible_width_m(d, L) = d · eff_h / L
反推焦距      lens_for_width_m(W,d) = eff_h · d / W
```
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # 无窗口后端：只出文件
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EFF_H_MM = 36.0                  # 横屏水平有效传感器（04 §二）

# 所有标注一律加白底：场景中心（案台/门/锚点/站位/机位）天然挤在一起，
# 不垫底的话文字会互相压住 —— 实测第一版中心区完全读不出来。
TXT_BOX = dict(facecolor="white", alpha=0.82, edgecolor="none", pad=1.2)

# 中文字体：按可用性回退，缺字时不让整张图崩掉
for _f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "SimSun"):
    try:
        matplotlib.rcParams["font.sans-serif"] = [_f] + list(
            matplotlib.rcParams.get("font.sans-serif", []))
        matplotlib.rcParams["axes.unicode_minus"] = False
        break
    except Exception:            # noqa: BLE001
        continue


# ── 光学（唯一来源：04 §二）─────────────────────────────────────────────
def fov_h_deg(lens_mm: float) -> float:
    return 2.0 * math.degrees(math.atan(EFF_H_MM / (2.0 * lens_mm)))


def visible_width_m(dist_m: float, lens_mm: float) -> float:
    return dist_m * EFF_H_MM / lens_mm


def lens_for_width_m(width_m: float, dist_m: float) -> float:
    return EFF_H_MM * dist_m / width_m


# ── 绘制 ────────────────────────────────────────────────────────────────
def _ellipse_arc(cx, cy, r, a0, a1, n=48):
    """视锥扇形的弧（度）。"""
    pts = [(cx, cy)]
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw(spec: dict, mode: str, out_dir: Path) -> list:
    ext = spec["extent"]
    x0, x1 = ext["x"]
    y0, y1 = ext["y"]
    grid = float(spec.get("grid_m", 1.0))
    sid = spec["scene_id"]

    fig, ax = plt.subplots(figsize=(16, 16 * (y1 - y0) / max(x1 - x0, 1e-6)), dpi=110)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_facecolor("#fafafa")

    # 1) 一米格
    xs = [x0 + i * grid for i in range(int((x1 - x0) / grid) + 1)]
    ys = [y0 + i * grid for i in range(int((y1 - y0) / grid) + 1)]
    for gx in xs:
        ax.axvline(gx, color="#e2e2e2", lw=0.6, zorder=0)
    for gy in ys:
        ax.axhline(gy, color="#e2e2e2", lw=0.6, zorder=0)
    ax.text(x1, y1, "  一格 = %.1f 米" % grid, ha="right", va="top",
            fontsize=11, color="#666", zorder=1)

    # 2) 场地实体块（有尺寸的矩形，标注米数）
    for s in spec.get("solids", []):
        w = s["x1"] - s["x0"]
        h = s["y1"] - s["y0"]
        ax.add_patch(Rectangle((s["x0"], s["y0"]), w, h,
                               facecolor=s.get("fill", "#d9d9d9"),
                               edgecolor="#333", lw=1.2, zorder=2))
        ax.text((s["x0"] + s["x1"]) / 2, (s["y0"] + s["y1"]) / 2,
                "%s\n%.2f×%.2f m" % (s.get("label", s.get("id", "")), w, h),
                ha="center", va="center", fontsize=8.5, zorder=9, bbox=TXT_BOX)

    # 3) 锚点物编号
    for a in spec.get("anchors", []):
        ax.plot(a["x"], a["y"], marker="s", ms=7, color="#7b1fa2", zorder=5)
        ax.annotate("%s %s" % (a["id"], a.get("label", "")),
                    (a["x"], a["y"]), textcoords="offset points", xytext=(7, 7),
                    fontsize=9, color="#7b1fa2", zorder=10, bbox=TXT_BOX)

    # 4) 动作轴线
    al = spec.get("axis_line")
    if al:
        ax.plot([al["x0"], al["x1"]], [al["y0"], al["y1"]],
                ls="-.", lw=1.6, color="#1565c0", zorder=4)
        ax.annotate(" " + al.get("label", "动作轴线"),
                    ((al["x0"] + al["x1"]) / 2, (al["y0"] + al["y1"]) / 2),
                    textcoords="offset points", xytext=(0, -26), ha="center",
                    fontsize=9.5, color="#1565c0", zorder=10, bbox=TXT_BOX)

    # 5) A/B 分界线 —— 必须贯穿全场并延伸到框外（§2.1 第 5 条）
    ab = spec.get("ab_line")
    if ab:
        dx, dy = ab["x1"] - ab["x0"], ab["y1"] - ab["y0"]
        n = math.hypot(dx, dy) or 1.0
        L = max(x1 - x0, y1 - y0) * 3.0            # 远远伸出画面
        ex0, ey0 = ab["x0"] - dx / n * L, ab["y0"] - dy / n * L
        ex1, ey1 = ab["x1"] + dx / n * L, ab["y1"] + dy / n * L
        ax.plot([ex0, ex1], [ey0, ey1], lw=2.4, color="#c62828", zorder=4)
        # 标签放在【框内】的那一段上，否则会被画到画面外面看不见
        lx, ly = ab["x0"] - dx / n * 1.6, ab["y0"] - dy / n * 1.6
        ax.annotate(" " + ab.get("label", "A/B 分界"), (lx, ly),
                    textcoords="offset points", xytext=(-10, 0), ha="right",
                    va="center", fontsize=9.5, color="#c62828", zorder=10,
                    bbox=TXT_BOX)
        # A / B 两侧字母：放远一点，别被站位点压住
        px, py = -dy / n, dx / n
        mx, my = (ab["x0"] + ab["x1"]) / 2, (ab["y0"] + ab["y1"]) / 2
        span = max(x1 - x0, y1 - y0) * 0.30
        for sign, lab in ((1, "A 侧（机位只能在这一侧）"), (-1, "B 侧（禁止越轴）")):
            ax.plot([mx, mx + sign * px * span], [my, my + sign * py * span],
                    lw=0.8, color="#c62828", alpha=0.45, zorder=4)
            ax.text(mx + sign * px * span, my + sign * py * span, lab,
                    fontsize=11, color="#c62828", ha="center", va="center",
                    alpha=0.95, zorder=10, bbox=TXT_BOX)

    # 6) 站位点 + 朝向箭头
    for a in spec.get("actors", []):
        ax.plot(a["x"], a["y"], marker="o", ms=11, color="#2e7d32", zorder=7)
        ang = math.radians(a.get("facing_deg", 90))
        ax.annotate("", xy=(a["x"] + 0.7 * math.cos(ang), a["y"] + 0.7 * math.sin(ang)),
                    xytext=(a["x"], a["y"]),
                    arrowprops=dict(arrowstyle="-|>", lw=2.2, color="#2e7d32"), zorder=7)
        ax.annotate("%s %s" % (a["id"], a.get("label", "")),
                    (a["x"], a["y"]), textcoords="offset points", xytext=(10, -14),
                    fontsize=10, color="#1b5e20", zorder=11, bbox=TXT_BOX)

    # 7) 机位 + 朝向箭头 + 视锥扇形（§2.1 第 6 条）
    for c in spec.get("cameras", []):
        yaw = c["yaw_deg"]
        lens = c.get("lens_mm")
        dist = c.get("dist_m")
        if lens:
            half = fov_h_deg(lens) / 2.0
            r = dist if dist else 3.0
            ax.add_patch(Polygon(_ellipse_arc(c["x"], c["y"], r, yaw - half, yaw + half),
                                 closed=True, facecolor="#ff9800", alpha=0.22,
                                 edgecolor="#e65100", lw=1.0, zorder=5))
            vw = visible_width_m(dist, lens) if dist else float("nan")
            sub = "%s\n%dmm / %.2fm\n可见宽 %.2fm" % (c["id"], lens, dist or 0, vw)
        else:
            sub = c["id"]
        ang = math.radians(yaw)
        ax.annotate("", xy=(c["x"] + 0.8 * math.cos(ang), c["y"] + 0.8 * math.sin(ang)),
                    xytext=(c["x"], c["y"]),
                    arrowprops=dict(arrowstyle="-|>", lw=2.0, color="#e65100"), zorder=6)
        ax.plot(c["x"], c["y"], marker="^", ms=11, color="#e65100", zorder=7)
        ax.annotate(sub, (c["x"], c["y"]), textcoords="offset points", xytext=(9, 9),
                    fontsize=8.5, color="#bf360c", zorder=11, bbox=TXT_BOX)

    ax.set_title("%s · %s  %s" % (sid, spec.get("name", ""),
                                  "平面调度图（plan）" if mode == "plan" else "机位调度图（cams）"),
                 fontsize=15)
    ax.set_xlabel("x（米，向东为正）")
    ax.set_ylabel("y（米，向北为正）")
    ax.grid(False)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("%s_%s.png" % (sid, mode))
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    return [out]


def main() -> int:
    ap = argparse.ArgumentParser(description="程序化绘制场景平面调度图 / 机位调度图")
    ap.add_argument("spec", help="场景规格 JSON 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认写到规格同级的 assets/SCN）")
    ap.add_argument("--mode", default="both", choices=["plan", "cams", "both"])
    args = ap.parse_args()

    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    if args.out:
        out_dir = Path(args.out)
    else:
        # 从规格路径往上推：<项目>/storyboard/xxx.json → <项目>/assets/SCN
        out_dir = spec_path.parent.parent / "assets" / "SCN"

    modes = ["plan", "cams"] if args.mode == "both" else [args.mode]
    made = []
    for m in modes:
        made += draw(spec, m, out_dir)
    for p in made:
        print("✅ %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
