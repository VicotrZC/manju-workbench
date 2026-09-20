#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""算力闸门 · 跑 GPU 之前的预检（**核心检查不需要连云**）。

为什么需要它：一次 GPU 任务的代价 = 租价 × 时间 + 你的等待。绝大多数浪费来自
**跑之前就能看出来**的错误：帧数不在网格、画布不是 32 倍数、LoRA 节点断开了、
提示词少了禁字幕句。

设计原则：**按「不变量」检查，不按「设计表」检查。**
  `.work/check_scene_workflows.py` 就是反面教材 —— 它硬编码一张设计表，结果表里写着
  已作废的 SCN_03，而正在用的 SCN_03b 根本不在表里，且必须连云才能跑，于是没人跑、
  也没人发现它过期了。
  不变量（帧数必须落在 17k+5、画布必须是 32 倍数…）**不会过期**。

用法:
    python .work/check_before_gpu.py                      # 查 workflows/ 下全部（离线）
    python .work/check_before_gpu.py workflows/scene      # 指定目录
    python .work/check_before_gpu.py --file a.json b.json # 指定文件
    python .work/check_before_gpu.py --online             # 额外看队列/显存
    python .work/check_before_gpu.py --json               # 机器可读（给子 agent 用）

退出码: 0=通过 ｜ 1=有 ERROR（**不许开跑**）｜ 2=只有 WARN

⚠️ 注意区分：仓库里已有一个 `.work/preflight.py`，那是**服务器上音频分离**的预检，
    与本脚本无关。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# ── 不变量（改这里 = 改全项目的合法口径；与 `规矩_新AI必读.md` §3 保持一致）──
H3_GRID = [5 + 17 * k for k in range(0, 22)]          # 5,22,39,…,362
# (步数, CFG) 已登记档位。前三个是正式档，后四个是 BUST_*_cfg* 的**有意对照实验**，
# 登记进来是为了消掉噪音 —— 噪音会让人无视警告，然后真异常也被无视（§8 的教训）。
LEGAL_SAMPLING = {
    (8, 1.0), (4, 1.0), (50, 4.0),                    # 正式
    (8, 1.5), (8, 2.0), (8, 4.0), (20, 4.0),          # 已登记的实验档
}
# 画布约束：**通用是 8 的倍数**（VAE 下采样）；**32 的倍数是 H3 的要求**，不是 Qwen 的。
# 2026-09-20 修正：第一版把 32 推广到所有画布，结果对 1328×1328 的角色卡误报 ——
# 那批卡是跑成功了的。规矩.md §8 说过：会误报的检查器比没有更糟。
CANVAS_MULTIPLE_GENERAL = 8
CANVAS_MULTIPLE_H3 = 32
NO_SUB_SENTENCE = "No subtitles, captions or on-screen text appear at any point."
FRONTEND_ONLY = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode",
                 "PreviewAny", "PreviewImage"}
# 画布上的说明便签 —— 它们的文字**不进模型**，绝不能参与提示词扫描。
# （2026-09-20：第一版没排除它们，对 3 个场景工作流误报了「书名号」错误。）
ANNOTATION_TYPES = {"MarkdownNote", "Note"}
SAMPLER_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
LATENT_TYPES = {"EmptySD3LatentImage", "EmptyLatentImage", "EmptyLatentImagePresets"}
H3_VIDEO_TYPES = {"MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"}
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

COST_PER_SEC = 1.58 / 3600.0   # 用户实际租价 ¥1.58/小时


class Report:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []
        self.warns: list[str] = []
        self.notes: list[str] = []

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warns.append(m)

    def note(self, m: str) -> None:
        self.notes.append(m)


def all_text(node: dict) -> str:
    out = []
    for v in (node.get("widgets_values") or []):
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return "\n".join(out)


def required_inputs(info: dict, ntype: str) -> set:
    """该节点类型「必填且必须靠连线提供」的输入名（控件不算）。"""
    spec = info.get(ntype, {}).get("input", {})
    out = set()
    for name, val in (spec.get("required") or {}).items():
        t = val[0] if isinstance(val, list) and val else None
        if isinstance(t, list) or t in WIDGET_TYPES:
            continue
        out.add(name)
    return out


def check_workflow(path: Path, info: dict | None = None) -> Report:
    rep = Report(path.name)
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        rep.err(f"JSON 解析失败：{exc!r}")
        return rep

    if "nodes" not in wf:
        rep.note("不是画布工作流（无 nodes 字段）—— 可能是 API JSON，跳过结构检查")
        return rep

    nodes = {n["id"]: n for n in wf["nodes"]}
    links = wf.get("links") or []

    # ── 连通性：**顶层 links 数组才是真源**。
    # 2026-09-20 实测：老工作流（外部导出/API 生成）的 outputs[].links 普遍为空
    # （某文件 17/17 全空、另一个 29 个槽位 27 个空），但 inputs[].link 与顶层 links 是齐的，
    # ComfyUI 也照跑。所以**不能**用 outputs[].links 判定"没接上"——那是误报。
    out_links: dict[int, set] = {}      # 节点 id -> {(slot, link_id)}
    in_links: dict[int, dict] = {}      # 节点 id -> {slot: link_id}
    link_ids: set = set()
    for l in links:
        if len(l) < 5:
            rep.err(f"links 里有格式不对的条目（长度 {len(l)}）：{l!r}")
            continue
        lid, src, sslot, dst, dslot = l[0], l[1], l[2], l[3], l[4]
        link_ids.add(lid)
        if src not in nodes or dst not in nodes:
            rep.err(f"link{lid} 端点节点不存在（{src}→{dst}）")
            continue
        if sslot >= len(nodes[src].get("outputs") or []):
            rep.err(f"link{lid} 起点 {src} 没有 output slot {sslot}")
        if dslot >= len(nodes[dst].get("inputs") or []):
            rep.err(f"link{lid} 终点 {dst} 没有 input slot {dslot}")
        out_links.setdefault(src, set()).add((sslot, lid))
        in_links.setdefault(dst, {})[dslot] = lid

    # inputs[].link 必须能在顶层 links 里找到，且确实指向本节点的这个槽位
    for nid, n in nodes.items():
        for i, slot in enumerate(n.get("inputs") or []):
            lid = slot.get("link")
            if lid is None:
                continue
            if lid not in link_ids:
                rep.err(f"节点 {nid}({n['type']}) 的 inputs[{i}] 引用了不存在的 link{lid}")
            elif in_links.get(nid, {}).get(i) != lid:
                rep.err(f"节点 {nid}({n['type']}) 的 inputs[{i}].link={lid} "
                        f"与顶层 links 对不上")

    # 2) 必填输入已连线（需要 /object_info，只有 --online 时做）
    if info:
        for n in wf["nodes"]:
            t = n["type"]
            if t not in info:
                if t not in FRONTEND_ONLY:
                    rep.err(f"节点 {n['id']} 类型 {t} 云端不存在（缺节点包？）")
                continue
            linked = {i["name"] for i in (n.get("inputs") or []) if i.get("link") is not None}
            miss = required_inputs(info, t) - linked
            if miss:
                rep.err(f"节点 {n['id']}({t}) 必填输入未连线：{sorted(miss)}")

    prompts, samplers, canvases = [], [], []
    for n in wf["nodes"]:
        t, wv = n["type"], (n.get("widgets_values") or [])
        if t not in ANNOTATION_TYPES:
            prompts.append(all_text(n))

        if t in SAMPLER_TYPES and len(wv) >= 4:
            try:
                samplers.append((n["id"], int(wv[2]), float(wv[3])))
            except (TypeError, ValueError):
                rep.warn(f"节点 {n['id']}({t}) 采样参数读不出来：{wv[:4]}")

        if t in LATENT_TYPES and len(wv) >= 2:
            try:
                canvases.append([int(wv[0]), int(wv[1])])
            except (TypeError, ValueError):
                pass

        if t in ("LoraLoaderModelOnly", "LoraLoader"):
            # ★ 真实踩过的坑：LoRA 可能「断开」而不是「旁路」——没有下游时改 mode 无效。
            # 但判定必须用**顶层 links**（见上），不能用 outputs[].links（那常为空，会误报）。
            connected = bool(out_links.get(n["id"]))
            enabled = n.get("mode", 0) == 0
            if not connected:
                rep.err(f"LoRA 节点 {n['id']} **没有连到任何下游**"
                        f"—— 此时改 mode 无效，LoRA 实际没生效")
            elif not enabled:
                rep.warn(f"LoRA 节点 {n['id']} 被旁路（mode={n.get('mode')}）")
            rep.note(f"LoRA：{wv[0] if wv else '?'}（接通={connected} 启用={enabled}）")

        if t == "SaveImage" and wv:
            rep.note(f"输出前缀：{wv[0]}")

    # 3) 采样档必须成对合法
    for nid, steps, cfg in samplers:
        if (steps, cfg) not in LEGAL_SAMPLING:
            rep.warn(f"节点 {nid} 采样 {steps} 步 / CFG {cfg} 不在已登记档位 "
                     f"{sorted(LEGAL_SAMPLING)}；若有意为之，请在 "
                     f"`规矩_新AI必读.md` §3 登记新档位")

    # 4) 画布必须是 8 的倍数（通用 VAE 下采样约束）
    for c in canvases:
        for v in c:
            if v % CANVAS_MULTIPLE_GENERAL != 0:
                rep.err(f"画布 {c} 有值不是 {CANVAS_MULTIPLE_GENERAL} 的倍数（{v}）"
                        f"—— VAE 下采样会出问题")

    # 5) H3 帧数必须落在 17k+5
    #    字段布局实测：widgets_values = [提示词, 宽, 高, **长度**, ...]
    #    （2026-09-20：第一版扫"第一个 5..3600 的整数"，结果把宽度 1344 当成帧数，误报。）
    for n in wf["nodes"]:
        if n["type"] in H3_VIDEO_TYPES:
            wv = n.get("widgets_values") or []
            if len(wv) < 4 or not all(isinstance(wv[i], int) for i in (1, 2, 3)):
                rep.warn(f"H3 节点 {n['id']} 的 widgets_values 布局与预期不同，"
                         f"帧数检查跳过：{wv[:5]!r}")
                continue
            w, h, length = wv[1], wv[2], wv[3]
            rep.note(f"H3 画布 {w}×{h}｜长度 {length} 帧 = {length / 24:.2f}s")
            if length not in H3_GRID:
                nxt = next((g for g in H3_GRID if g >= length), None)
                rep.err(f"H3 节点 {n['id']} 帧数 {length} 不在 17k+5 网格上"
                        f"（会被向上吸附到 {nxt} = {nxt / 24:.2f}s，多送 "
                        f"{(nxt - length) / 24:.2f}s）")
            for v in (w, h):
                if v % CANVAS_MULTIPLE_H3 != 0:
                    rep.err(f"H3 节点 {n['id']} 画布 {v} 不是 {CANVAS_MULTIPLE_H3} 的倍数"
                            f"（H3 官方要求分辨率取 32 的倍数）")

    # 6) 提示词扫描（**排除说明便签** —— 见 ANNOTATION_TYPES）
    joined = "\n".join(prompts)
    if "<d>" in joined and NO_SUB_SENTENCE not in joined:
        rep.err("提示词含 <d>（台词）但没有禁字幕句 —— H3 会把台词画成画面字幕。"
                f"要加的原句：{NO_SUB_SENTENCE}")
    for n in wf["nodes"]:
        if n["type"] in ANNOTATION_TYPES:
            continue
        t = all_text(n)
        if "「" in t or "」" in t:
            rep.err(f"节点 {n['id']}（{n['type']}）的提示词里有书名号「」"
                    f"—— 实测会被画进画面，删掉：…{t[max(0, t.find('「') - 30):t.find('「') + 30]}…")

    # 7) ★ Qwen-Image-Edit 的静默降级陷阱（ComfyUI issue #2681 / #2678）
    #    `TextEncodeQwenImageEdit*` **不接受尺寸参数**：它把参考图缩到硬编码的
    #    int(1024*1024) ≈ 1.05 MP（按源图宽高比），并把参考 token 与生成 token 放在
    #    **同一个居中坐标网格**上。网格不一样大 → 细节复制不过去 → 模型「重新合成」主体，
    #    表现是材质变塑料/CGI、印刷细节变泛化形状，而**什么都不报错**。
    #    来源：artokun/comfyui-mcp 的 qwen-image-edit skill（2026-09-20 经 web_search 找到）。
    edit_encoders = [n for n in wf["nodes"]
                     if n["type"].startswith("TextEncodeQwenImageEdit")]
    if edit_encoders:
        for n in wf["nodes"]:
            if n["type"] in LATENT_TYPES:
                wv = n.get("widgets_values") or []
                size = wv[:2] if len(wv) >= 2 else "?"
                mp = None
                if len(wv) >= 2 and all(isinstance(v, int) for v in wv[:2]):
                    mp = wv[0] * wv[1] / 1e6
                rep.warn(
                    f"edit 图（有 {edit_encoders[0]['type']}）却用了固定尺寸 latent {size}"
                    + (f" = {mp:.2f} MP" if mp else "")
                    + " —— 编码器派生的是 ~1.05 MP，网格不一致时模型会**重新合成主体**"
                      "（塑料感 / CGI 感 / 细节泛化）且**不报错**。"
                      "正确接法：LoadImage → FluxKontextImageScale →（TextEncode ＋ "
                      "VAEEncode）→ KSampler.latent_image。见 issue #2681")
        if not any(n["type"] == "FluxKontextImageScale" for n in wf["nodes"]):
            rep.warn("edit 图里没有 FluxKontextImageScale —— 它负责把源图缩到模型期望的 "
                     "~1.05 MP；缺了它，参考与输出的坐标网格可能对不上（#2681）")

    rep.note(f"节点 {len(nodes)}｜links {len(links)}｜"
             f"采样 {['%d步/CFG%s' % (s, c) for _, s, c in samplers] or '无'}｜"
             f"画布 {canvases or '无'}")
    return rep


def online_context() -> Report:
    """可选：连云看显存。云机关机时不算失败。"""
    rep = Report("__online__")
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=6) as r:
            st = json.loads(r.read().decode("utf-8"))
        dev = (st.get("devices") or [{}])[0]
        free = dev.get("vram_free", 0) / 2**30
        total = dev.get("vram_total", 0) / 2**30
        rep.note(f"ComfyUI 在线：显存空闲 {free:.1f}/{total:.1f} GB")
        if free < 20:
            rep.warn(f"显存只剩 {free:.1f} GB —— H3 约需 28 GB、Qwen 约需 20 GB，"
                     f"先确认上一个任务已完全卸载（一次只跑一个占显存的任务）")
    except Exception:  # noqa: BLE001
        rep.note("ComfyUI 不在线（8188 无响应）—— 离线检查照常有效")
    return rep


def fetch_object_info() -> dict | None:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=None,
                    help="要检查的目录。**默认扫 projects/*/workflows/（新范式）"
                         "＋ workflows/scene/（旧式）**；别默认扫整个 workflows/ —— "
                         "历史产物会把真问题淹掉")
    ap.add_argument("--all", action="store_true",
                    help="审计模式：扫整个 workflows/（历史文件的问题只作参考，不是待办）")
    ap.add_argument("--file", nargs="*", default=None)
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--json", action="store_true", help="机器可读输出（给子 agent 用）")
    ap.add_argument("--summary", action="store_true",
                    help="每个文件一行：档位 / 画布 / LoRA / 错误数")
    ap.add_argument("--graph", action="store_true",
                    help="打印节点图：每个节点的类型 / 关键 widget / 上游连线（做 A/B 前对齐变量用）")
    args = ap.parse_args()

    if args.file:
        targets = [Path(f) if Path(f).is_absolute() else ROOT / f for f in args.file]
    else:
        if args.all:
            d = ROOT / "workflows"
        elif args.dir:
            d = Path(args.dir)
            if not d.is_absolute():
                d = ROOT / d
        else:
            # 默认：**所有项目的工作流** ＋ 旧式 workflows/scene（若有）。
            # 新范式下项目工作流在 projects/<项目>/workflows/，不再集中在 workflows/。
            d = None
        if d is None:
            targets = []
            roots = [p / "workflows" for p in (ROOT / "projects").glob("*")
                     if (p / "workflows").is_dir()]
            if (ROOT / "workflows" / "scene").is_dir():
                roots.append(ROOT / "workflows" / "scene")
            for r in roots:
                targets += [p for p in r.rglob("*.json")
                            if "object_info" not in p.name and "package" not in p.name]
            targets = sorted(set(targets))
        else:
            targets = sorted(p for p in d.rglob("*.json")
                             if "object_info" not in p.name and "package" not in p.name)

    if not targets:
        print("没找到要检查的工作流 JSON。")
        print("  默认会扫 projects/*/workflows/（新范式）+ workflows/scene/（旧式）。")
        print("  也可以显式指定：python .work/check_before_gpu.py <目录>")
        print("                python .work/check_before_gpu.py --file a.json b.json")
        return 0

    info = fetch_object_info() if args.online else None
    reps = [check_workflow(p, info) for p in targets]
    onl = online_context() if args.online else None

    if args.graph:
        for p in targets:
            wf = json.loads(p.read_text(encoding="utf-8"))
            if "nodes" not in wf:
                print(f"{p.name}: 不是画布工作流")
                continue
            nodes = {n["id"]: n for n in wf["nodes"]}
            print(f"\n=== {p.name} ===")
            for n in wf["nodes"]:
                t = n["type"]
                if t in ANNOTATION_TYPES:
                    continue
                # 关键 widget：字符串截断，其余原样
                wv = []
                for v in (n.get("widgets_values") or []):
                    if isinstance(v, str):
                        wv.append(f'"{v[:48]}{"…" if len(v) > 48 else ""}"')
                    else:
                        wv.append(json.dumps(v, ensure_ascii=False))
                src = []
                for i in (n.get("inputs") or []):
                    if i.get("link") is None:
                        continue
                    l = next((x for x in (wf.get("links") or []) if x[0] == i["link"]), None)
                    if l:
                        on = nodes.get(l[1], {}).get("type", "?")
                        src.append(f"{i['name']}←{l[1]}:{on}")
                mode = "" if n.get("mode", 0) == 0 else f"  [mode={n['mode']} 旁路]"
                print(f"  {n['id']:>3} {t:<38}{mode}")
                if wv:
                    print(f"      widget: {' | '.join(wv)}")
                if src:
                    print(f"      连线  : {', '.join(src)}")
        return 0

    if args.summary:
        def grab(notes, key, sep="｜"):
            for n in notes:
                if key in n:
                    v = n.split(key, 1)[1]
                    return v.split(sep)[0].strip()
            return "-"
        print(f"{'工作流':<34} {'采样':<16} {'画布':<16} {'LoRA':<10} 错/警")
        print("-" * 96)
        for r in reps:
            samp = grab(r.notes, "采样 ")
            canv = grab(r.notes, "画布 ")
            lora = sum(1 for n in r.notes if n.startswith("LoRA："))
            h3 = next((n for n in r.notes if n.startswith("H3 画布")), "")
            if h3:
                canv = h3.replace("H3 ", "").split("｜")[0]
            print(f"{r.name:<34} {samp:<16} {canv:<16} {lora:<10} "
                  f"{len(r.errors)}/{len(r.warns)}")
            for e in r.errors:
                print(f"      [ERROR] {e}")
            for w in r.warns:
                print(f"      [WARN ] {w}")
        n_err = sum(len(r.errors) for r in reps)
        print(f"\n合计 {len(reps)} 个文件、{n_err} 个 ERROR")
        return 1 if n_err else (2 if any(r.warns for r in reps) else 0)

    if args.json:
        verdict = ("FAIL" if any(r.errors for r in reps)
                   else "WARN" if any(r.warns for r in reps) else "PASS")
        print(json.dumps({
            "verdict": verdict,
            "files": [{"name": r.name, "errors": r.errors,
                       "warns": r.warns, "notes": r.notes} for r in reps],
            "online": {"notes": onl.notes, "warns": onl.warns} if onl else None,
        }, ensure_ascii=False, indent=2))
    else:
        n_err = n_warn = 0
        for r in reps:
            if not (r.errors or r.warns):
                print(f"✅ {r.name}")
            else:
                print(f"{'❌' if r.errors else '⚠️ '} {r.name}")
            for x in r.notes:
                print(f"     · {x}")
            for x in r.errors:
                print(f"     [ERROR] {x}")
            for x in r.warns:
                print(f"     [WARN ] {x}")
            n_err += len(r.errors)
            n_warn += len(r.warns)
        if onl:
            for x in onl.notes:
                print(f"ℹ️  {x}")
            for x in onl.warns:
                print(f"⚠️  {x}")
        print()
        if n_err:
            print(f"⛔ 不通过：{n_err} 个 ERROR、{n_warn} 个 WARN —— **先修，不要开跑**")
        elif n_warn:
            print(f"⚠️  通过但有 {n_warn} 个 WARN —— 确认无害再开跑")
        else:
            print("✅ 全部通过，可以开跑")

    if any(r.errors for r in reps):
        return 1
    return 2 if any(r.warns for r in reps) else 0


if __name__ == "__main__":
    sys.exit(main())
