#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""【唯一执行器】把项目里的画布工作流 JSON 跑成产物。

    python tools/run.py <项目名> <工作流名> [--out 目录] [--timeout 秒]
    python tools/run.py 买肉 SCN_01_stall_hero
    python tools/run.py --list 买肉
    python tools/run.py --refresh-layout          # 联网刷新 widget 布局缓存
    python tools/run.py 买肉 SCN_01_stall_hero --skip-gate   # 明确跳过门禁（不推荐）

范式见 `规矩.md` §2：**新任务 = 新增/修改一个工作流 JSON，不要新写 .py。**
本文件是那"一个 py"。它取代了散落的 `make_*.py` / `nc_*.py` 生成脚本，
以及此前手写的 `.work/comfy_api.py`（同样的逻辑，但那个写死了盘符）。

为什么工作流是「画布 JSON」而不是 API JSON：
  画布 JSON（nodes/links/widgets_values）**用户可以直接在 ComfyUI 里打开看状态**，
  而 `POST /prompt` 只收 API 格式。本文件负责在两者之间转换 —— 画布文件是源，API 是派生物。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 路径：一律从脚本位置往上推，**不许写死盘符**（规矩.md §0）─────────────
ROOT = Path(__file__).resolve().parents[1]
LAYOUT_FILE = Path(__file__).resolve().parent / "widget_layout.json"
BASE = os.environ.get("COMFY_BASE", "http://127.0.0.1:8188")   # 隧道本地端

FRONTEND_ONLY = {"MarkdownNote", "Note"}       # 只存在于画布，永不发给 API


class ValidationError(RuntimeError):
    pass


# ── widget 布局：缓存 + 联网校验 ─────────────────────────────────────────
def load_layout() -> dict:
    if not LAYOUT_FILE.exists():
        raise ValidationError(
            f"缺少 widget 布局缓存 {LAYOUT_FILE}。\n"
            f"联网时用 `python tools/run.py --refresh-layout --write` 生成。")
    return json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))


def _get(path: str, timeout: int = 60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _widget_names(spec: dict) -> list:
    """从 /object_info 的一个节点规格里推出 widget 的位置顺序。

    ComfyUI 前端的顺序 = required 里「非连线型」输入 → optional 里「非连线型」输入，
    保持 dict 定义顺序。**这只是一个推导**，所以它只用来和缓存表对账，不直接替换。
    """
    out = []
    for group in ("required", "optional"):
        for name, val in (spec.get("input", {}).get(group) or {}).items():
            t = val[0] if isinstance(val, list) and val else None
            if isinstance(t, list):          # 下拉框 = 控件
                out.append(name)
            elif t in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                out.append(name)
                # 前端会给这种 INT 注入一格「control_after_generate」
                opts = val[1] if len(val) > 1 and isinstance(val[1], dict) else {}
                if opts.get("control_after_generate"):
                    out.append(None)
    return out


def refresh_layout(write: bool = False) -> int:
    """联网，把 /object_info 推导出来的布局与缓存表对账。**不一致就报出来，不静默改。**"""
    try:
        info = _get("/object_info", timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 连不上 ComfyUI（{BASE}）：{exc!r}")
        return 1
    cache = load_layout()
    diff = 0
    for cls, cached in sorted(cache.items()):
        if cls not in info:
            print(f"⚠️  缓存里有 {cls}，但后端 /object_info 没有这个节点类型")
            diff += 1
            continue
        derived = _widget_names(info[cls])
        if derived != cached:
            diff += 1
            print(f"❌ {cls}")
            print(f"     缓存：{cached}")
            print(f"     推导：{derived}")
    extra = sorted(set(info) - set(cache))
    print(f"\n对账完成：{len(cache)} 个类，{diff} 处不一致；"
          f"后端另有 {len(extra)} 个类型未在缓存中（正常，只登记我们在用的）")
    if diff and write:
        print("⚠️  --write 已给出但存在不一致 —— **不自动覆盖**。请人工确认后改 "
              f"{LAYOUT_FILE}。")
        return 1
    if write:
        LAYOUT_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(f"✅ 布局缓存无变化，已重写 {LAYOUT_FILE}")
    return 0 if diff == 0 else 1


# ── 画布 JSON → API prompt ──────────────────────────────────────────────
def to_api_prompt(wf: dict, layout: dict) -> dict:
    """转换。**宁可报错也不猜**。"""
    nodes = wf["nodes"]
    links = {l[0]: l for l in wf.get("links", [])}
    by_id = {n["id"]: n for n in nodes}

    for n in nodes:
        for inp in n.get("inputs") or []:
            if "widget" in inp:
                raise ValidationError(
                    f"节点 {n['id']}（{n.get('type')}）把某个 widget 转成了输入口；"
                    f"转换器不处理这种情况")

    prompt = {}
    for n in nodes:
        if n.get("mode", 0) != 0:          # 旁路/静音 → 不发
            continue
        cls = n.get("type")
        if cls in FRONTEND_ONLY:
            continue
        if cls == "Reroute":
            raise ValidationError("Reroute 节点需要先解连线，暂不支持")
        if cls not in layout:
            raise ValidationError(
                f"未知节点类型 {cls}（节点 {n['id']}）。"
                f"把它加进 {LAYOUT_FILE} 再用。")
        spec = layout[cls]
        wv = n.get("widgets_values") or []
        if len(wv) != len(spec):
            raise ValidationError(
                f"节点 {n['id']}（{cls}）：widgets_values 有 {len(wv)} 个，"
                f"布局表期望 {len(spec)} 个 {spec}")

        inputs = {}
        for name, val in zip(spec, wv):
            if name is not None:
                inputs[name] = val
        for inp in n.get("inputs") or []:
            lid = inp.get("link")
            if lid is None:
                continue
            l = links.get(lid)
            if l is None:
                raise ValidationError(
                    f"节点 {n['id']} 的输入 {inp.get('name')} 引用了不存在的 link{lid}")
            inputs[inp["name"]] = [str(l[1]), l[2]]
        prompt[str(n["id"])] = {"class_type": cls, "inputs": inputs}

    for n in nodes:
        if n.get("mode", 0) == 0:
            continue
        for out in n.get("outputs") or []:
            if out.get("links"):
                raise ValidationError(
                    f"被旁路的节点 {n['id']} 仍然连着下游 {out['links']}；先重新接线")
    return prompt


# ── 提交 / 等待 / 下载 ──────────────────────────────────────────────────
def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise ValidationError(f"HTTP {e.code} from {path}: {body[:900]}") from None


def submit(api_prompt: dict) -> str:
    res = _post("/prompt", {"prompt": api_prompt, "client_id": "dsh-automation"})
    errs = res.get("node_errors") or {}
    if errs:
        raise ValidationError("node_errors: " + json.dumps(errs, ensure_ascii=False)[:1200])
    return res["prompt_id"]


def wait(prompt_id: str, timeout_s: int = 900, poll_s: float = 4.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hist = _get(f"/history/{prompt_id}", timeout=30)
        entry = hist.get(prompt_id)
        if entry:
            st = entry.get("status", {})
            if st.get("completed") or st.get("status_str") in ("success", "error"):
                return entry
        time.sleep(poll_s)
    raise TimeoutError(f"prompt {prompt_id} 在 {timeout_s}s 内没结束")


def output_files(entry: dict) -> list:
    files = []
    for out in (entry.get("outputs") or {}).values():
        files.extend(out.get("images") or [])
        for key in ("gifs", "videos", "audio"):
            files.extend(out.get(key) or [])
    return files


def download(item: dict, dest_dir: Path, attempts: int = 4) -> Path:
    """带重试：实测隧道偶发 WinError 10054（连接被重置），
    一次抖动不该让整批 8 件在最后一步全废。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    q = urllib.parse.urlencode({
        "filename": item["filename"],
        "subfolder": item.get("subfolder", ""),
        "type": item.get("type", "output"),
    })
    dest = dest_dir / item["filename"]
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(f"{BASE}/view?{q}", timeout=180) as r:
                data = r.read()
            if not data:
                raise IOError("空响应")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)          # 原子落盘，避免半截文件被当成产物
            return dest
        except Exception as e:         # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(2 + 3 * i)
    raise IOError(f"下载失败（试了 {attempts} 次）：{last}")


# ── 项目解析 ────────────────────────────────────────────────────────────
SLUG_RE = re.compile(r"^\s*slug\s*[:：]\s*(\S+)", re.MULTILINE)


def project_dir(name: str) -> Path:
    """按文件夹名**或 slug** 找项目。

    slug 写在 `项目卡.md` 里（例如 `slug: meishi`），这样命令不用敲全名 ——
    书名带全角标点，天天敲 `美食：全市巡摆，馋哭食客` 是折磨。
    """
    root = ROOT / "projects"
    d = root / name
    if d.is_dir():
        return d
    for card in sorted(root.glob("*/项目卡.md")):
        m = SLUG_RE.search(card.read_text(encoding="utf-8", errors="replace"))
        if m and m.group(1) == name:
            return card.parent
    avail = sorted(p.name for p in root.iterdir() if p.is_dir())
    raise ValidationError(f"没有这个项目（也不是任何项目的 slug）：{name}\n现有项目：{avail}")


def list_workflows(proj: str) -> int:
    d = project_dir(proj)
    wfs = sorted((d / "workflows").glob("*.json")) if (d / "workflows").is_dir() else []
    print(f"项目 {proj} 的工作流（{len(wfs)} 个）：")
    for p in wfs:
        size = p.stat().st_size
        print(f"  - {p.stem}   ({size} B)")
    if not wfs:
        print("  （空）把画布工作流 JSON 放进 "
              f"{d / 'workflows'} —— 可以直接从 ComfyUI 导出")
    return 0


def run_gate(wf_path: Path) -> bool:
    """提交之前跑门禁。**这是规矩 §7 的强制项。**"""
    gate = ROOT / ".work" / "check_before_gpu.py"
    if not gate.exists():
        print("⚠️  找不到门禁脚本 .work/check_before_gpu.py —— 跳过（请补上）")
        return True
    import subprocess
    r = subprocess.run([sys.executable, str(gate), "--file", str(wf_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout or "")
    if r.returncode == 1:
        print("⛔ 门禁不通过 —— 拒绝提交。修好后重跑，或明确用 --skip-gate。")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="唯一执行器：跑项目里的画布工作流")
    ap.add_argument("project", nargs="?", help="项目名（projects/ 下的文件夹名）")
    ap.add_argument("workflow", nargs="?", help="工作流名（不带 .json）")
    ap.add_argument("--list", action="store_true", help="列出该项目的工作流")
    ap.add_argument("--out", default=None, help="产物目录，默认 projects/<项目>/outputs")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--refresh-layout", action="store_true")
    ap.add_argument("--show-layout", metavar="类名",
                    help="联网看某个节点类型推导出来的 widget 布局（表里没有的类用这个）")
    ap.add_argument("--write", action="store_true", help="配合 --refresh-layout")
    ap.add_argument("--dry-run", action="store_true", help="只转换不提交")
    args = ap.parse_args()

    if args.show_layout:
        try:
            info = _get("/object_info", timeout=60)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ 连不上 ComfyUI（{BASE}）：{exc!r}")
            return 1
        if args.show_layout not in info:
            print(f"❌ 后端没有这个节点类型：{args.show_layout}")
            return 1
        print(f"{args.show_layout}: "
              f"{json.dumps(_widget_names(info[args.show_layout]), ensure_ascii=False)}")
        return 0
    if args.refresh_layout:
        return refresh_layout(write=args.write)
    if not args.project:
        ap.error("需要项目名（或用 --list / --refresh-layout）")
    if args.list or not args.workflow:
        return list_workflows(args.project)

    proj = project_dir(args.project)
    wf_path = proj / "workflows" / f"{args.workflow}.json"
    if not wf_path.exists():
        return list_workflows(args.project) or 1

    if not args.skip_gate and not run_gate(wf_path):
        return 1

    out_dir = Path(args.out) if args.out else proj / "outputs"
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    api = to_api_prompt(wf, load_layout())
    print(f"✅ 转换通过：{len(api)} 个节点 → API 格式")
    if args.dry_run:
        print("（--dry-run，未提交）")
        return 0

    pid = submit(api)
    print(f"▶ 已提交 prompt_id={pid}，等待中…")
    entry = wait(pid, timeout_s=args.timeout)
    st = entry.get("status", {})
    if st.get("status_str") == "error":
        raise ValidationError("运行失败：" + json.dumps(st, ensure_ascii=False)[:900])
    saved = [download(i, out_dir) for i in output_files(entry)]
    print(f"✅ 完成，{len(saved)} 个产物落 {out_dir}")
    for p in saved:
        print(f"   - {p.name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValidationError, TimeoutError, IOError) as exc:
        print(f"❌ {exc}")
        sys.exit(1)
