#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""流程审计闸门 —— **唯一审计入口**（规矩.md §7）。

    python tools/pipeline_audit.py chain      <项目>                 # 层链 + 节拍覆盖
    python tools/pipeline_audit.py preflight  <项目> <工作流名>       # 机械不变量 + 出审计包
    python tools/pipeline_audit.py packet     <项目> <工作流名>       # 打印给子 agent 的简报
    python tools/pipeline_audit.py seal       <项目> <主题> <判定.json>  # 校验并封存 agent 判定
    python tools/pipeline_audit.py verify     <项目> <工作流名>       # 提交前硬闸门（run.py 调它）
    python tools/pipeline_audit.py postflight <项目>                 # 项目完成后的流程审计包
    python tools/pipeline_audit.py status     <项目>

## 为什么要有这个文件

2026-09-21 买肉场成片整体跑偏（写实画风 / 全片无人说话 / 开场"骑车赶到菜市"整拍丢失 /
GEO 空间地图没有逐字进提示词）。**这些没有一条是"生成失败"，全部是"上游文本没有落到提示词里"，
而当时没有任何程序在看这件事。** 所以本文件把「戏 → 分镜 → 提示词」的对应关系做成可复现的检查。

## 两道 agent 闸门（规矩 §7 子 agent 监督协议）

| 闸门 | 时机 | 干什么 |
|---|---|---|
| **preflight** | **每一次生成之前**（生图 / 生视频都算） | 子 agent 读「戏 ＋ 分镜表 ＋ GEO ＋ 工作流提示词」，逐拍判"这一拍到底进没进这条提示词" |
| **postflight** | **一个项目/一场做完之后** | 子 agent 审**流程本身**：哪一步没拦住、要新增哪条检查 |

**子 agent 做算力闸门，不做审美裁判**（规矩 §7 原话）。画风好不好看、脸像不像，仍然只有用户能判。

## 封条机制（为什么 agent 的判定不会被绕过）

1. `preflight` 产出**审计包** `.work/audit/packets/<主题>.packet.json`
2. 子 agent 据此写判定 JSON
3. `seal` **由本程序**把被审文件的 `sha256` 写进封条 → `review/audits/<主题>.audit.json`
4. `run.py` 提交前调 `verify`：封条缺失 / 过期（被审文件变了）/ 判定 fail / 机械 ERROR 未被豁免
   → **拒绝提交**

**改了提示词就必须重新审** —— 这不是靠自觉，是靠哈希。

## 边界（规矩 12）

**本程序报"通过" ≠ 内容合格。** 它只回答"文本有没有落到提示词里"，
不回答"好不好看"。所有会误报的检查都先在已知样本上跑过（规矩 14）。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── 路径：一律从 __file__ 往上推，不写死盘符（规矩 §0）──────────────────
ROOT = Path(__file__).resolve().parents[1]
PACKET_DIR = ROOT / ".work" / "audit" / "packets"

# ── H3 六段式：顺序固定（h3res/guide_ref_en.md）────────────────────────
H3_FIELDS = ["subject_definitions", "summary", "retention_analysis",
             "detailed_description", "overall_soundscape", "non_diegetic_music"]

NO_SUB_STEM = "No subtitles, captions or on-screen text appear at any point"

# 提示词里出现这些 = 声明本镜无人说话
NO_SPEECH_RE = re.compile(
    r"no dialogue|nobody speaks|nobody'?s lips move|no one speaks|no voices|is silent",
    re.I)
# 宣告有台词的官方写法（规矩 §9：<d> 与禁字幕句**不是二选一**）
SPEECH_TAG_RE = re.compile(r"<d>\s*\[")

H3_GRID = 17          # 帧数必须落在 17k+5
H3_SHORT_SIDE = 768   # H3 画布短边


class Report:
    """一份检查结果。**ERROR 才拦提交**，WARN 只提示，PENDING 是"步骤没走到，轮不到它"。

    ## 为什么要有 PENDING（2026-09-21 加）

    「引用了一个**还没产出**的产物」和「引用了一个**根本不存在**的产物」是两件事：

    - 镜头表必须在出图**之前**就登记首帧文件名 —— 否则没法拿它出图。**先有鸡还是先有蛋。**
      登记的时候文件当然不在。这不是错误，是**还没轮到**。
    - 真到了要推 GPU 的那一刻文件还不在 —— **那才是错误**，必须拦死（S8）。

    原来两种都报 ERROR，于是 `S2 分镜` 永远过不去：它引用的首帧是 S6 才出的东西。
    把「还没做」判成「做错了」，模型会被要求改一个它根本改不了的东西，
    然后**跑满轮数、白烧额度、最后记一份假失败**。
    """

    def __init__(self, title: str):
        self.title = title
        self.items: list[dict] = []

    def add(self, level: str, code: str, msg: str, **extra):
        self.items.append({"level": level, "code": code, "msg": msg, **extra})

    def error(self, code, msg, **extra):
        self.add("ERROR", code, msg, **extra)

    def warn(self, code, msg, **extra):
        self.add("WARN", code, msg, **extra)

    def info(self, code, msg, **extra):
        self.add("INFO", code, msg, **extra)

    def pending(self, code, msg, **extra):
        """产物还没产出 —— **不算错**，但要在该拦的时候被提成错（见 `promote_pending`）。"""
        self.add("PENDING", code, msg, **extra)

    @property
    def errors(self) -> list[dict]:
        return [i for i in self.items if i["level"] == "ERROR"]

    @property
    def warns(self) -> list[dict]:
        return [i for i in self.items if i["level"] == "WARN"]

    @property
    def pendings(self) -> list[dict]:
        return [i for i in self.items if i["level"] == "PENDING"]

    def promote_pending(self, why: str = "") -> int:
        """把 PENDING 提成 ERROR。**在"必须要它在"的那一关调用**（S8 推 GPU 之前）。"""
        n = 0
        for it in self.items:
            if it["level"] == "PENDING":
                it["level"] = "ERROR"
                if why:
                    it["msg"] = f"{it['msg']}（{why}）"
                n += 1
        return n

    def ok(self) -> bool:
        return not self.errors

    def dump(self) -> dict:
        return {"title": self.title, "ok": self.ok(),
                "errors": self.errors, "warns": self.warns,
                "pending": self.pendings,
                "items": self.items}

    def print(self):
        """打印。

        ⚠️ **PENDING 必须和 WARN 分开显示。** 2026-09-21 实测：原来一律打 `⚠️`，
        于是「首帧还没出」这 9 条形产物项看起来像 9 个**警告**，
        而标题里的 `WARN 0` 又对不上 —— **数字和符号互相矛盾，读的人只会懵。**
        """
        mark = "✅" if self.ok() else "⛔"
        tail = f"ERROR {len(self.errors)} ／ WARN {len(self.warns)}"
        if self.pendings:
            tail += f" ／ 待产出 {len(self.pendings)}"
        print(f"\n{mark} {self.title} —— {tail}")
        for i in self.items:
            if i["level"] == "INFO":
                continue
            tag = {"ERROR": "❌", "WARN": "⚠️ ", "PENDING": "⏳"}[i["level"]]
            print(f"  {tag} [{i['code']}] {i['msg']}")
            for k, v in i.items():
                if k not in ("level", "code", "msg"):
                    print(f"        {k}: {v}")


# ── 小工具 ─────────────────────────────────────────────────────────────
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def read(p: Path) -> str:
    # utf-8-sig：**容忍 BOM**。Windows 上 PowerShell 的 `Set-Content -Encoding UTF8`
    # 和不少编辑器都会写 BOM，用 utf-8 硬读会在 json.loads 处炸掉 ——
    # 而判定 JSON 正是子 agent / 人手写的，不能因为一个 BOM 就判"封条无效"。
    return p.read_text(encoding="utf-8-sig", errors="replace")


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def noscript_chars(s: str) -> int:
    """算占比时的字符数：去掉所有空白。"""
    return len(re.sub(r"\s+", "", s or ""))


def _key(s: str) -> str:
    """比对台词用的归一化键：去掉空白与中英标点，只留字。"""
    return re.sub(r"[\s，。！？、,.!?；;：:「」『』“”\"'（）()\[\]【】…—\-]", "", s or "")


def image_size(p: Path):
    """PNG / JPEG 的像素尺寸。读不出来返回 None（不猜）。"""
    try:
        b = p.read_bytes()[:65536]
    except OSError:
        return None
    if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR":
        return (int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big"))
    if b[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return (int.from_bytes(b[i + 7:i + 9], "big"),
                        int.from_bytes(b[i + 5:i + 7], "big"))
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
    return None


def project_dir(name: str) -> Path:
    root = ROOT / "projects"
    d = root / name
    if d.is_dir():
        return d
    for card in sorted(root.glob("*/项目卡.md")):
        m = re.search(r"^\s*slug\s*[:：]\s*(\S+)", read(card), re.MULTILINE)
        if m and m.group(1) == name:
            return card.parent
    avail = sorted(p.name for p in root.iterdir() if p.is_dir())
    raise SystemExit(f"❌ 没有这个项目（也不是任何项目的 slug）：{name}\n现有项目：{avail}")


def load_rules(proj: Path) -> dict:
    f = proj / "audit_rules.json"
    if not f.exists():
        raise SystemExit(
            f"❌ 缺少 {f.name} —— 审计需要项目自己的锁定件（画风句/签名标记/否定锁）。\n"
            f"   照 tools/pipeline_audit.py 顶部的 schema 建一份。")
    return json.loads(read(f))


# ── 戏文件解析（剧本层是**唯一**的节拍来源）─────────────────────────────
BEAT_HDR = re.compile(r"^\*\*\s*(B\d+)\s*[｜|]\s*(.*?)\*\*\s*$")
CH_ROW = re.compile(r"^\|\s*\*\*(VO|对白|UI|花字|画面)\*\*\s*\|\s*(.*?)\s*\|\s*(\d*)\s*\|")


def _inner(cell: str) -> str:
    """取「」内的正文。

    戏的表里写的是 `闫清：「老板，这猪肉怎么卖啊！」` —— **说话人是说话人，台词是台词**。
    官方 H3 写法是 `(S1)` 当说话人、正文进 `<d>[Chinese] …</d>`。
    若把「闫清：」也算进台词的字符数，字数核算和"逐句核对"都会系统性偏大
    （子 agent 2026-09-21 实测：B2 被算成 51 字，实际 34 字）。
    """
    m = re.search(r"[「『“\"](.+?)[」』”\"]", cell)
    return m.group(1).strip() if m else cell.strip()


def parse_script(path: Path) -> dict:
    """把 `*_戏.md` 的九拍表解析成机器可读的节拍表。

    **戏是节拍的唯一权威** —— 分镜只能认领，不能新增（pipeline/docs/02 §规则七）。
    """
    beats: dict[str, dict] = {}
    counts: dict[str, dict[str, list[int]]] = {}
    cur = None
    for line in read(path).splitlines():
        m = BEAT_HDR.match(line.strip())
        if m:
            cur = m.group(1)
            beats[cur] = {"id": cur, "header": m.group(2).strip(),
                          "channels": {"VO": [], "对白": [], "UI": [], "花字": [], "画面": []}}
            counts[cur] = {"VO": [], "对白": []}
            continue
        if cur is None:
            continue
        r = CH_ROW.match(line.strip())
        if r:
            ch, cell, declared = r.group(1), r.group(2), r.group(3)
            beats[cur]["channels"][ch].append(_inner(cell))
            if ch in ("VO", "对白"):
                # **优先用戏自己写的「字数」列** —— 那是它的决算口径（§三 就是按它算的）
                counts[cur][ch].append(int(declared) if declared
                                       else len(re.sub(r"\s", "", _inner(cell))))
    for b in beats.values():
        b["has_dialogue"] = bool(b["channels"]["对白"])
        b["has_vo"] = bool(b["channels"]["VO"])
        b["dialogue_chars"] = sum(counts[b["id"]]["对白"])
        b["vo_chars"] = sum(counts[b["id"]]["VO"])
    return beats


# ── 分镜表（机器可读的镜头表）──────────────────────────────────────────
SHOT_REQUIRED = ["id", "beats", "shot_size", "lens_mm", "dist_m", "frames",
                 "first_frame", "framing_en", "workflow"]


def on_screen(prompt: str, c: dict) -> bool:
    """这个角色在不在这条提示词里。**用 `match` 里登记的称呼判**，
    因为提示词写的是 `<Subject 2>` / `the butcher`，不是内部编号。"""
    low = prompt.lower()
    keys = c.get("match") or ([c["name"]] if c.get("name") else [])
    return any(k and str(k).lower() in low for k in keys)


def all_shot_tables(proj: Path, rules: dict) -> list[str]:
    """本项目**所有**场次的镜头表（相对路径，已排序）。

    2026-09-21 拆场次后新增：一个项目可以有多个场次，
    项目级的 `shot_table` 单值**只够单场次项目用**。
    下面这些命令拿不到"当前场次"的上下文，就靠这个函数逐场次跑：
    `check` / `postflight` / `sync-prompts` / `seal` / `verify`。
    """
    declared = str(rules.get("shot_table") or "").replace("\\", "/")
    found = sorted(str(p.relative_to(proj)).replace("\\", "/")
                   for p in (proj / "storyboard").glob("*_镜头表.json"))
    if not found:
        return [declared] if declared else []
    # 把登记过的那份排在最前（单场次项目的默认命中）
    return sorted(found, key=lambda r: (r != declared, r))


def table_for_workflow(proj: Path, rules: dict, wf_name: str) -> str | None:
    """这条工作流属于哪一场（返回那一场的镜头表路径）。找不到返回 None。"""
    if not wf_name:
        return None
    for rel in all_shot_tables(proj, rules):
        f = proj / rel
        if not f.exists():
            continue
        try:
            tbl = json.loads(read(f))
        except ValueError:
            continue
        for s in tbl.get("shots") or []:
            if wf_name in (s.get("workflow"), s.get("first_frame_workflow")):
                return rel
    return None


def load_shot_table(proj: Path, rules: dict,
                    materials: str = "error",
                    table_rel: str | None = None) -> tuple[dict, Report]:
    """读镜头表并核它登记的产物在不在。

    `materials`：见 `check_chain` —— `"pending"` 时「产物还没出」记 PENDING 不记 ERROR。
    `table_rel`：读哪一份镜头表。不给就用项目级 `shot_table`（单场次项目的行为）。
    """
    rep = Report("分镜表（镜头表 JSON）")

    def _missing(code: str, msg: str, **extra):
        (rep.pending if materials == "pending" else rep.error)(code, msg, **extra)

    rel = table_rel or rules.get("shot_table", "storyboard/镜头表.json")
    f = proj / rel
    if not f.exists():
        rep.error("SHOT-00", f"分镜表不存在：{rel}",
                  fix="分镜层必须先出机器可读的镜头表；没有它，节拍覆盖无法核对")
        return {"shots": []}, rep
    tbl = json.loads(read(f))
    shots = tbl.get("shots") or []
    if not shots:
        rep.error("SHOT-00", f"分镜表 {rel} 里没有任何镜头")
    seen = set()
    for s in shots:
        sid = s.get("id", "?")
        for k in SHOT_REQUIRED:
            if k not in s or s[k] in (None, "", []):
                rep.error("SHOT-01", f"镜头 {sid} 缺字段 `{k}`",
                          fix="01_资产规范/规矩 §1：镜头表必须含机位与取景的机器可读值")
        if sid in seen:
            rep.error("SHOT-01", f"镜头号重复：{sid}")
        seen.add(sid)
        ff = s.get("first_frame")
        if ff:
            cand = [proj / "assets" / ff, proj / "outputs" / ff,
                    proj / "storyboard" / ff, proj / ff]
            if not any(c.exists() for c in cand):
                # **命名漂移**：找不到时别只说"找不到" —— 去 outputs/ 找带本镜号的产物，
                # 把真名报出来。否则一个从来没存在过的名字能一辈子挂在表里
                # （并且 WF-16 会因为"两边都指向同一个不存在的名字"而静默通过）。
                drift = sorted(p.name for p in (proj / "outputs").glob(f"*{sid}*")
                               if p.is_file() and p.suffix.lower() in
                               (".png", ".jpg", ".jpeg", ".webp"))
                fw = s.get("first_frame_workflow")
                _missing(
                    "SHOT-02",
                    f"镜头 {sid} 的首帧还没出：{ff}"
                    + (f"（将由 {fw} 出图）" if fw else ""),
                    searched=[str(c.relative_to(proj)) for c in cand],
                    likely_real=[str((proj / 'outputs' / d).relative_to(proj))
                                 for d in drift[:8]] or None,
                    fix=(f"出首帧：`pipeline.py gen {proj.name} S6` 会写 "
                         f"workflows/{fw}.json，再 `run.py` 推云机出图"
                         if fw else "镜头表里登记 `first_frame_workflow`，再出图"))
        wfn = s.get("workflow")
        if wfn:
            wf_file = proj / "workflows" / f"{wfn}.json"
            if not wf_file.exists():
                _missing("SHOT-04",
                         f"镜头 {sid} 的工作流还没写：workflows/{wfn}.json",
                         fix=f"`pipeline.py gen {proj.name} S6` 会按镜头表逐镜生成；"
                             f"**一个镜头一条工作流，不许反复改写同一个文件** —— "
                             f"被覆盖掉的那一镜的提示词就永远无法审计、无法复现了")
    return tbl, rep


# ── GEO 空间地图：英文块必须**逐字**进每条提示词（01_资产规范 §2.3）────
def geo_block(proj: Path, rules: dict) -> str:
    rel = rules.get("geo_file")
    if not rel:
        return ""
    f = proj / rel
    if not f.exists():
        return ""
    lines = read(f).splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "英文版" in ln:
            start = i
            break
    if start is None:
        return ""
    body, fence = [], False
    for ln in lines[start:]:
        if ln.strip().startswith("```"):
            if fence:
                break
            fence = True
            continue
        if fence:
            body.append(ln)
    return "\n".join(body).strip()


# ── 工作流读取 ─────────────────────────────────────────────────────────
def load_workflow(path: Path) -> dict:
    wf = json.loads(read(path))
    wf["_links"] = {l[0]: (l[1], l[2]) for l in wf.get("links", [])}
    wf["_by_id"] = {n["id"]: n for n in wf.get("nodes", [])}
    return wf


def upstream_text(wf: dict, node_id, input_name: str, depth: int = 0) -> str:
    """顺着顶层 links 往上游找第一个带文本的节点。

    规矩 §8 坑 1：**outputs[].links 普遍为空，判连通性必须用顶层 links。**
    """
    if depth > 8 or node_id is None:
        return ""
    n = wf["_by_id"].get(node_id)
    if n is None:
        return ""
    # ⚠️ 判据**必须包括 edit 链的文本节点**：`TextEncodeQwenImageEdit(Plus)` 也是提示词。
    # （子 agent 2026-09-21 实测：只认 CLIPTextEncode 会让 5 条 edit 链被判"空提示词"，
    #  然后 return 掉、后面所有检查全部跳过 —— 静默漏检比误报更危险。）
    if n.get("type") in ("CLIPTextEncode", "TextEncodeQwenImageEdit",
                         "TextEncodeQwenImageEditPlus"):
        wv = n.get("widgets_values") or []
        return wv[0] if wv and isinstance(wv[0], str) else ""
    for inp in n.get("inputs") or []:
        if inp.get("name") != input_name:
            continue
        lid = inp.get("link")
        if lid is None:
            continue
        src = wf["_links"].get(lid)
        if src:
            return upstream_text(wf, src[0], "text", depth + 1)
    # 单输入节点（如 ConditioningZeroOut）
    for inp in n.get("inputs") or []:
        lid = inp.get("link")
        if lid is None:
            continue
        src = wf["_links"].get(lid)
        if src:
            t = upstream_text(wf, src[0], "text", depth + 1)
            if t:
                return t
    return ""


def split_h3_fields(prompt: str):
    """六段式切分。返回 (fields, order)。"""
    names = H3_FIELDS
    marks = []
    for m in re.finditer(r"(?m)^\s*([a-z_]+)\s*:\s*$", prompt):
        if m.group(1) in names:
            marks.append((m.group(1), m.start(), m.end()))
    fields, order = {}, []
    for i, (n, _s, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(prompt)
        fields[n] = prompt[e:end].strip()
        order.append(n)
    return fields, order


def h3_nodes(wf: dict) -> list[dict]:
    return [n for n in wf.get("nodes", [])
            if str(n.get("type", "")).startswith("MiniMaxH3")]


# ══════════════════════════════════════════════════════════════════════
#  第一道：层链 + 节拍覆盖
# ══════════════════════════════════════════════════════════════════════
def tbl_scene_id(tbl: dict) -> str:
    """镜头表里声明的场次号。**读文件里写的那个**，不按文件名猜。"""
    return str(tbl.get("scene") or "").strip()


def scene_plan(rules: dict, scene_id: str) -> dict:
    """本场次用哪份戏、负责哪几拍。

    `audit_rules.json` 的 `beat_scope`：

        "beat_scope": {
          "SCN-01": {"script": "script/EP02_SC01_…_戏.md", "beats": ["B1","B2","B3","B4"]},
          "SCN-02": {"script": "script/EP02_SC02_凌晨空街_戏.md", "beats": ["B1"]}
        }

    **为什么一场一份戏**：拆场次之后两场的节拍号各自从 B1 起（各场自己的戏文件是
    节拍的唯一权威）。所以"戏里有哪些拍"必须**按场次去读它自己那份戏**，
    不能拿项目级的那一份去套两场 —— 否则 SCN-02 的 B1 会被判成"戏里不存在的节拍"。

    没登记就返回 `{}` = 不限制（单场次项目的旧行为，向后兼容）。
    """
    entry = (rules.get("beat_scope") or {}).get(scene_id)
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, (list, tuple)):     # 老写法：只给拍号，戏用项目级那份
        return {"script": rules.get("script"), "beats": list(entry)}
    return {}


def beat_scope(rules: dict, scene_id: str) -> set[str]:
    """本场次负责的节拍集合（空集 = 不限制）。"""
    return {str(b).strip() for b in (scene_plan(rules, scene_id).get("beats") or [])}


def check_chain(proj: Path, rules: dict, materials: str = "error",
                table_rel: str | None = None) -> tuple[Report, dict]:
    """层链与节拍覆盖。

    `materials`：**引用了一个还没产出的产物，算什么？**

    | 值 | 用在哪 | 「首帧还没出」 | 「工作流还没写」 |
    |---|---|---|---|
    | `"pending"` | **S2 分镜 / S3 验分镜** —— 两者都排在生产步骤前面 | PENDING | PENDING |
    | `"error"`   | **S6 写完 / S8 推 GPU 之前** —— 此刻不在就是真错 | ERROR | ERROR |

    **为什么必须分档（2026-09-21 实测教训）**：

    这条链查的三样东西 —— 首帧图、镜头工作流、首帧工作流 —— **全是 S6 才产出的**，
    而 S2（分镜）和 S3（验分镜）都排在 S6 **前面**，两者都不产出这些文件。
    原判据一律报 ERROR，于是：

    - **S2 永远过不去** → 模型跑满 3 轮、白烧额度、最后记一份**假失败**；
    - **S3 永远过不去** → 而 S3 是 S4 的依赖 → **整条线在第一步就死锁**。

    判据错位比漏检更坏：它不让任何东西通过，却让人以为"是模型不行"。
    真到了要推 GPU 那一刻文件还不在，**S8 会把它提成 ERROR 拦死** —— 防线没有丢。
    """
    rep = Report(f"层链与节拍覆盖 · {proj.name}")

    def _missing(code: str, msg: str, **extra):
        """产物不在：按 materials 决定报 PENDING 还是 ERROR。"""
        (rep.pending if materials == "pending" else rep.error)(code, msg, **extra)

    # ── 本场次用哪份戏 ──
    # 拆场次后**一场一份戏**（各场节拍号各自从 B1 起）。所以先读镜头表拿到场次号，
    # 再按 `beat_scope` 找这一场该读哪份戏；没登记才回落到项目级那份。
    tbl, srep = load_shot_table(proj, rules, materials=materials, table_rel=table_rel)
    rep.items.extend(srep.items)
    shots = tbl.get("shots") or []
    sid_now = tbl_scene_id(tbl)
    plan = scene_plan(rules, sid_now)

    rel_script = plan.get("script") or rules.get("script")
    if not rel_script or not (proj / rel_script).exists():
        rep.error("CHAIN-01",
                  f"剧本层文件缺失：{rel_script}"
                  + (f"（场次 {sid_now} 在 beat_scope 里登记的戏）" if plan.get("script") else ""),
                  fix="先出戏，再出分镜")
        return rep, {}

    beats = parse_script(proj / rel_script)
    rep.info("BEAT-00", f"场次 {sid_now} 读的戏：{rel_script}"
                        f"　共 {len(beats)} 个节拍：{'、'.join(beats)}")

    # ── 本场次**该管哪几拍** ──
    # 2026-09-21 拆出「凌晨空街」场次后新增。一个项目可以有多个场次（不同地点＝不同场次，
    # 行规如此），每份镜头表只认领**本场那几拍**；要求每一份都覆盖全部节拍是错的。
    # 但**跨场次的覆盖不能松**：漏掉的拍必须仍被抓住，否则正是我们要防的那种事故。
    scope_ids = beat_scope(rules, sid_now)
    scene_beats = {b: v for b, v in beats.items() if not scope_ids or b in scope_ids}
    if scope_ids:
        unknown = sorted(scope_ids - set(beats))
        if unknown:
            rep.error("BEAT-03",
                      f"`beat_scope` 给场次 {sid_now} 登记的节拍，在它自己那份戏里不存在：{unknown}",
                      fix="节拍号写错了；`beat_scope` 只能引用**该场戏里**真实存在的 B 号")
        rep.info("BEAT-03", f"本场次（{sid_now}）负责的节拍："
                            f"{'、'.join(sorted(scene_beats)) or '（空）'}")
    else:
        rep.warn("BEAT-03",
                 f"`beat_scope` 没登记场次 {sid_now} —— 本场按『要覆盖戏里全部 "
                 f"{len(beats)} 拍』判。**多场次项目必须登记**，否则每一场都会被误报漏拍",
                 fix="在 audit_rules.json 的 beat_scope 里给每个场次写清 script 与 beats")

    # ── WF-19 画风锁的出处（**项目级，只报一次**）──
    # 子 agent 2026-09-21：`audit_rules.json` 里那条 H3 英文锁是程序自己加的，项目卡里没有。
    # **拿一句没人拍板的话当闸门判据，就是又一次"我自己编验收标准"。**
    card = proj / "项目卡.md"
    if card.exists():
        card_txt = norm_ws(read(card))
        for nm, txt in (rules.get("style_locks") or {}).items():
            if txt and norm_ws(txt) not in card_txt:
                rep.error("WF-19",
                          f"画风锁「{nm}」在 项目卡.md 里**找不到逐字出处**",
                          fix="未拍板的锁不能当闸门判据：要么让用户在项目卡里逐字确认它，"
                              "要么把它从 audit_rules.json 删掉")

    # ── 节拍覆盖：**这是"骑车赶到菜市整拍丢失"那类事故的唯一防线** ──
    # 先把**全项目**每一拍归哪一场算出来：串场认领要能报出"它属于哪一场"，
    # 那比"戏里没这一拍"有用得多（2026-09-21：原先 BEAT-02 先命中，
    # BEAT-04 永远轮不到，诊断退化成"拍号写错了"）。
    other_scenes: dict[str, str] = {}
    for other_id in (rules.get("beat_scope") or {}):
        if other_id == sid_now:
            continue
        for b in beat_scope(rules, other_id):
            other_scenes.setdefault(b, other_id)

    claimed: dict[str, list[str]] = {b: [] for b in beats}
    for s in shots:
        for b in s.get("beats") or []:
            # 判据的**先后顺序决定诊断质量**（2026-09-21 两轮才摆对）：
            #   ① 全项目都没有这个拍号 → BEAT-02「根本不存在」（最严重，先报）
            #   ② 它属于别的场次        → BEAT-04「串场了，它属于 SCN-0x」
            #   ③ 其余                  → 本场正常认领
            # 反过来写的话，一个不存在的 B9 会被报成"不属于本场次"，
            # 指向"去改 beat_scope"，而真正该做的是把拍号改对。
            if b not in beats and b not in other_scenes:
                rep.error("BEAT-02",
                          f"镜头 {s.get('id')} 认领了**全项目都不存在**的节拍 {b}",
                          fix="分镜不许新增剧情决定（pipeline/docs/02 规则七）；"
                              "拍号写错了就照该场戏文件里的 B 号改")
            elif scope_ids and b not in scope_ids:
                rep.error("BEAT-04",
                          f"镜头 {s.get('id')} 认领了 {b}，但这一拍**不属于本场次**"
                          + (f"，它属于场次 {other_scenes[b]}" if b in other_scenes
                             else f"（本场只管 {'、'.join(sorted(scope_ids))}）"),
                          fix="拆场次后节拍要各归各场；要么改镜头表，要么改 beat_scope")
            else:
                claimed[b].append(s.get("id"))

    for bid, b in scene_beats.items():
        if not claimed[bid]:
            rep.error("BEAT-01",
                      f"节拍 {bid}「{b['header']}」**没有任何镜头认领** —— 这一拍会整段消失在成片里",
                      fix="要么补镜头，要么回戏层删掉这一拍；不许默默吞掉")

    # ── 首帧血缘（SHOT-05）：**成片的画风由首帧决定，不由 H3 提示词决定** ──
    # 2026-09-21 实测：H3 的 detailed_description 里画风句好好地在最前面，
    # 首帧是写实的 → 成片就是写实的。所以画风闸门必须掐在**出首帧的那条工作流**上。
    _style_checked: set[str] = set()
    _ff_owner: dict[str, list[str]] = {}
    for s in shots:
        fw = s.get("first_frame_workflow")
        if not fw:
            rep.error("SHOT-05", f"镜头 {s.get('id')} 没登记 `first_frame_workflow`",
                      fix="首帧是哪条工作流出的一定要写下来，否则画风无从追溯")
            continue
        _ff_owner.setdefault(fw, []).append(s.get("id"))
        if not (proj / "workflows" / f"{fw}.json").exists():
            _missing("SHOT-05", f"镜头 {s.get('id')} 的首帧工作流还没写：{fw}",
                     fix=f"`pipeline.py gen {proj.name} S6` 会写它；"
                         f"首帧是哪条工作流出的一定要写下来，否则画风无从追溯")
            continue
        if fw in _style_checked:          # 四镜同源时只报一次，不刷屏
            continue
        _style_checked.add(fw)
        sub, _pk = check_workflow(proj, fw, rules, {"shots": [], "beats": {}})
        # **身份类（WF-07/08）与否定枚举（WF-22）也要透传** —— 脸是在首帧定下来的，
        # 首帧工作流才是身份检查真正该掐的地方（子 agent 2026-09-21）。
        # ⚠️ **沿用子条目的 level，不许一律升成 ERROR**，也不许全挂在"画风闸门"名下
        # —— WF-22 本是 WARN，WF-07/08 也不是画风问题（同一轮子 agent 指出）。
        PROP = {
            "WF-02": ("SHOT-05", "首帧画风锁定句"),
            "WF-03": ("SHOT-05", "首帧画风句位置"),
            "WF-04": ("SHOT-05", "首帧画风句占比"),
            "WF-07": ("SHOT-07", "首帧缺身份锚"),
            "WF-08": ("SHOT-07", "首帧缺正向否定锁"),
            "WF-22": ("SHOT-08", "首帧提示词里有否定枚举"),
        }
        for it in sub.items:
            if it["code"] in PROP:
                code, what = PROP[it["code"]]
                rep.add(it["level"], code,
                        f"{what}不过（镜头表登记的首帧出自 {fw}）："
                        f"[{it['code']}] {it['msg']}",
                        detail={k: v for k, v in it.items()
                                if k not in ("level", "code", "msg")})

    # ── SHOT-06 首帧工作流串档：一条首帧工作流不该被 2 镜以上登记 ──
    # 子 agent 2026-09-21 提出。同一条工作流跑多镜 = 出完就改提示词再出下一镜，
    # 中间那镜的提示词**没有留档就没了**。本项目的 S02 就是这么丢的。
    for fw, ids in _ff_owner.items():
        if len(ids) > 1:
            rep.error("SHOT-06",
                      f"首帧工作流 `{fw}` 被 {len(ids)} 个镜头共用：{'、'.join(ids)}",
                      fix="一条首帧工作流只跑一镜。共用意味着改提示词再跑，"
                          "上一镜的提示词没留档就丢了 —— 跑 sync-prompts 先归档")

    # ── 资产先于分镜（01_资产规范 §〇 铁律：无图不进分镜）──
    for key in ("characters", "scenes"):
        for aid, a in (rules.get(key) or {}).items():
            for f in a.get("files", []):
                if not (proj / "assets" / f).exists() and not (proj / "outputs" / f).exists():
                    rep.error("CHAIN-02",
                              f"资产 {aid}（{a.get('name','')}）的文件不在位：{f}",
                              fix="无图不进分镜")

    # ── 总时长 ──
    total = sum(int(s.get("frames") or 0) for s in shots)
    fps = tbl.get("fps") or 24
    if total:
        rep.info("SHOT-03", f"{len(shots)} 镜共 {total} 帧 ＝ {total / fps:.2f} 秒")

    return rep, {"beats": beats, "shots": shots, "fps": fps,
                 "total_frames": total,
                 "table": table_rel or rules.get("shot_table"),
                 "script": rel_script}


# ══════════════════════════════════════════════════════════════════════
#  第二道：单条工作流的机械不变量
# ══════════════════════════════════════════════════════════════════════
def check_workflow(proj: Path, wf_name: str, rules: dict, chain: dict) -> tuple[Report, dict]:
    rep = Report(f"工作流不变量 · {wf_name}")
    wf_path = proj / "workflows" / f"{wf_name}.json"
    if not wf_path.exists():
        rep.error("WF-00", f"工作流不存在：workflows/{wf_name}.json")
        return rep, {}
    wf = load_workflow(wf_path)
    nodes = wf.get("nodes", [])

    # 本工作流对应镜头表里的哪一镜（没有就是 None）。
    # ⚠️ **必须在任何用到它的检查之前算出来** —— 否则 `shot` 未绑定就崩。
    shot = next((s for s in (chain.get("shots") or [])
                 if s.get("workflow") == wf_name or s.get("id") == wf_name), None)

    # ── 这条工作流是不是「某个镜头的工作流」？──
    # **不是镜头工作流就跳过场次相关的检查。**
    # 子 agent 2026-09-21 实测：26 条工作流报出 90 条 ERROR，其中 75 条是误报 ——
    # 因为画风探针（STYLE_*）、稳定性验证（STAB_*）本来就不属于任何场次，
    # 拿「GEO 块在不在」「签名标记写没写」去要求它们是错的。
    # **会误报的检查器比没有检查器更糟**（规矩 §5.C 第 14 条）。
    table_wfs = {s.get("workflow") for s in (chain.get("shots") or [])}
    is_shot_wf = shot is not None or wf_name in table_wfs
    if not is_shot_wf:
        rep.info("SCOPE-00",
                 "本工作流未在任何镜头表里登记（画风探针／稳定性验证／首帧工作流）"
                 "→ 场次相关检查 WF-05/07/08/09/09b/10/16/18/20 已跳过")


    h3 = h3_nodes(wf)
    lat = [n for n in nodes if n.get("type") in
           ("EmptySD3LatentImage", "EmptyLatentImage", "EmptyLatentImagePresets")]

    # ── 取正向提示词 ──
    if h3:
        prompt = (h3[0].get("widgets_values") or [""])[0] or ""
        kind = "h3"
    else:
        sampler = next((n for n in nodes if n.get("type") in
                        ("KSampler", "KSamplerAdvanced", "SamplerCustom",
                         "SamplerCustomAdvanced")), None)
        prompt = upstream_text(wf, sampler["id"], "positive") if sampler else ""
        kind = "t2i"
    if not prompt.strip():
        rep.error("WF-00", "取不到正向提示词（空）")
        return rep, {}

    styled = prompt          # 算画风占比的默认范围
    fields, order = ({}, [])

    # ── WF-01 六段式 ──
    if kind == "h3":
        fields, order = split_h3_fields(prompt)
        missing = [f for f in H3_FIELDS if f not in fields]
        if missing:
            rep.error("WF-01", f"H3 六段式缺段：{missing}",
                      fix="h3res/guide_ref_en.md：六段顺序固定，缺段会被当普通文本")
        if order and order != [f for f in H3_FIELDS if f in order]:
            rep.error("WF-01", f"H3 六段式顺序不对：{order}")
        styled = fields.get("detailed_description", prompt)

    # ── WF-02/03/04 画风锁定句（**买肉场成片的头号病根**）──
    # 三条互相独立：**是否逐字**、**在不在最前面**、**占比够不够**。
    # 第 2、3 条即使第 1 条不过也要量 —— 因为"被改写"和"被淹没"是两个病，得分开报。
    #
    # ⚠️ **画风探针与稳定性验证工作流要跳过这三条。**
    # 子 agent 2026-09-21：STYLE_I_H_mature 是用户选定画风的**来源**，
    # 拿"画风句占比不足"去判它 ERROR 是荒谬的 —— 探针本身就是标尺。
    locks = rules.get("style_locks") or {}
    skip_style = any(fnmatch.fnmatch(wf_name, g)
                     for g in (rules.get("style_gate_skip_globs") or []))
    if skip_style:
        rep.info("WF-02", f"{wf_name} 是画风探针/稳定性验证工作流 → WF-02/03/04 跳过")
        locks = {}
    np_styled = norm_ws(styled)
    hit_name, pos = None, None
    for nm, txt in locks.items():
        if txt and norm_ws(txt) in norm_ws(prompt):
            hit_name, pos = nm, np_styled.find(norm_ws(txt))
            break
    style_len = None
    if hit_name is None and not skip_style:
        rep.error("WF-02",
                  "**画风锁定句没有逐字出现**（项目卡写明「照抄，不许改写」）",
                  registered=list(locks),
                  fix="照抄项目卡 §画风锁定句，一个字都不许改")
        # 退一步：用锁定句的开头当锚点定位，把"位置"和"占比"照样量出来
        for nm, txt in locks.items():
            if not txt:
                continue
            ntx = norm_ws(txt)
            for k in (12, 10, 8):
                i = np_styled.find(ntx[:k])
                if i >= 0:
                    hit_name, pos, style_len = nm, i, len(ntx)
                    break
            if pos is not None:
                break
    else:
        style_len = len(norm_ws(locks[hit_name])) if hit_name else None

    if pos is not None and pos >= 0:
        if pos > 20:
            rep.error("WF-03",
                      f"画风锁定句（{hit_name}）**不在描述段的最前面**"
                      f"（在第 {pos} 字处，描述段共 {noscript_chars(styled)} 字）",
                      fix="实测根因：画风句吊在长场景描述最后会被淹没。"
                          "STYLE_I 探针 366 字里占 33% → 生效；"
                          "FF_EP02SC01_shot 805 字里占 9% → 不生效")
        ratio = (style_len or 0) / max(1, noscript_chars(styled))
        floor = (rules.get("style_ratio_min") or {}).get(kind, 0.0)
        if ratio < floor:
            rep.error("WF-04",
                      f"画风句占比 {ratio:.1%} 低于下限 {floor:.0%}"
                      f"（{style_len} / {noscript_chars(styled)} 字）",
                      fix="要么把画风句提前，要么砍场景描述的字数")
        else:
            rep.info("WF-04", f"画风句占比 {ratio:.1%}（下限 {floor:.0%}）")

    # ── WF-19 画风锁必须能在项目卡里找到逐字出处 ──
    # 子 agent 2026-09-21 提出：`audit_rules.json` 里那条 H3 英文锁是**程序自己加的**，
    # 项目卡里没有。**拿一句没人拍板的话当闸门判据，就是又一次"我自己编验收标准"。**
    # ⚠️ 这是**项目级**问题 —— 在 `check_chain` 里报一次，不逐工作流重复刷屏。

    # ── WF-22 正向提示词里不许堆否定枚举（CFG 1.0 下无效，还稀释画风句占比）──
    # 子 agent 2026-09-21 实测：FF 首帧提示词末尾那串「没有招牌、没有价签文字…」
    # 没有拦住横幅上的中文，反而是首帧出乱码字的同一条提示词。
    NEG_WORDS = ("没有", "不要", "不许", "禁止", "无字")
    wl = rules.get("negative_phrase_whitelist") or []
    hits = [w for w in NEG_WORDS if w in prompt and w not in wl]
    if hits:
        rep.warn("WF-22",
                 f"正向提示词里出现否定枚举 {hits}（共 {sum(prompt.count(w) for w in hits)} 处）",
                 fix="规矩 §10：CFG 1.0 下负向词完全无效，写进正向只是白占字数、稀释画风句。"
                     "确实需要保留的，登记到 audit_rules.json 的 negative_phrase_whitelist")

    # ── WF-05 GEO 空间地图必须逐字进 detailed_description（§2.3）──
    geo = geo_block(proj, rules) if is_shot_wf else ""
    if geo:
        if norm_ws(geo) not in norm_ws(prompt):
            rep.error("WF-05",
                      "**GEO 空间地图英文块没有逐字进提示词**（01_资产规范 §2.3 要求一字不改）",
                      fix="把 storyboard/GEO空间地图.md §二 的整块贴进 detailed_description")
        else:
            rep.info("WF-05", "GEO 英文块已逐字锁定")
    elif is_shot_wf:
        rep.warn("WF-05", "audit_rules.json 没登记 geo_file，跨镜几何无从核对")

    # ── WF-06 禁字幕句（**只对 H3 视频成立**）──
    # 子 agent 2026-09-21：t2i 静帧没有"字幕"这回事，无条件执行会误报 18 条。
    # 只要求句干在（允许后面追加限定，例如"…other than the video on the phone screen"），
    # 免得把合法的变体误报成缺失（规矩 §14）。
    if kind == "h3" and NO_SUB_STEM not in prompt:
        rep.error("WF-06", "缺禁字幕句",
                  expect=NO_SUB_STEM,
                  fix="规矩 §9：<d> 与禁字幕句**不是二选一**，两个都要有")

    # ── WF-07 签名标记（§1.3 跨镜识别锚）──
    for cid, c in (rules.get("characters") or {}).items():
        if skip_style or not on_screen(prompt, c):
            continue
        sig = c.get("signature")
        if sig and norm_ws(sig).lower() not in norm_ws(prompt).lower():
            rep.error("WF-07",
                      f"{cid}（{c.get('name','')}）出场了，但**签名标记没写进提示词**：{sig}",
                      fix="§1.3：签名标记是跨镜认出同一个人的唯一锚，必须逐镜写")

    # ── WF-08 否定锁必须写在正向（CFG 1.0 负向无效）──
    for cid, c in (rules.get("characters") or {}).items():
        if skip_style or not on_screen(prompt, c):
            continue
        for lock in c.get("positive_locks") or []:
            if norm_ws(lock).lower() not in norm_ws(prompt).lower():
                rep.error("WF-08",
                          f"{cid}（{c.get('name','')}）缺正向否定锁：`{lock}`",
                          fix="规矩 §10：CFG 1.0 下负向词完全无效，"
                              "「不要什么」必须写进正向")

    # ── WF-09 台词保真（**买肉场成片的第二号病根**）──
    if shot is not None:
        beats = chain.get("beats") or {}
        owned = [b for b in (shot.get("beats") or []) if b in beats]
        expects_speech = any(beats[b]["has_dialogue"] for b in owned)
        has_tag = bool(SPEECH_TAG_RE.search(prompt))
        denies = bool(NO_SPEECH_RE.search(prompt))
        if expects_speech and denies:
            rep.error("WF-09",
                      "**这一镜认领的节拍里有对白，提示词却声明「无人说话」** —— "
                      "整场戏会被做成默片",
                      beats_with_dialogue=[b for b in owned if beats[b]["has_dialogue"]],
                      fix="躲烧字幕只能写 No subtitles，**不能把台词删掉**；"
                          "台词照官方写 <d>[Chinese] …</d> 并保留禁字幕句")
        elif expects_speech and not has_tag:
            rep.error("WF-09",
                      "这一镜有对白，但提示词里没有 `<d>[…]` 台词标注",
                      fix="h3res/guide_ref_en.md：台词写 <d>[Chinese] 原文</d>")
        elif not expects_speech and not denies:
            rep.warn("WF-09", "这一镜无对白，但提示词没有显式声明无人说话（容易漂出人声）")

        # **逐条核对，不是"有 <d> 就算过"**（子 agent 2026-09-21 提出的漏检）：
        # 三句对白只写进去一句也能过旧版 WF-09。
        # 口径（同一轮子 agent 纠正）：**判据是"这句原文必须落在某个 `<d>…</d>` 里"**，
        # 不是"在提示词里随便出现过" —— 否则照官方写法写对了它也会永远报错。
        if expects_speech:
            lines = []
            for b in owned:
                if b in beats:
                    lines += beats[b]["channels"]["对白"] + beats[b]["channels"]["VO"]
            dblocks = re.findall(r"<d>(.*?)</d>", prompt, re.S)
            inside = _key(" ".join(dblocks))
            missing_lines = [x for x in lines if _key(x) not in inside]
            if missing_lines:
                rep.error("WF-09b",
                          f"这一镜有 {len(missing_lines)} 条台词/VO 的原文没落进 `<d>…</d>`",
                          missing=missing_lines,
                          got_d_blocks=len(dblocks),
                          fix="戏层写了的每一句都要有落点；漏一句就等于改了戏。"
                              "写法见 h3res/guide_ref_en.md："
                              "<Subject 3> (S1) says, <d>[Chinese] 原文</d>")

    # ── WF-20 语音密度：这一镜的时长装不装得下这一拍的语音 ──
    # 戏 §三 自己写死的口径：语速 5.50 汉字/秒、密度上限 75%。
    if shot is not None:
        beats = chain.get("beats") or {}
        owned = [b for b in (shot.get("beats") or []) if b in beats]
        nchar = sum(beats[b]["dialogue_chars"] + beats[b]["vo_chars"] for b in owned)
        rate = rules.get("speech_rate_cps")
        dur = shot.get("duration_s") or (
            (shot.get("frames") or 0) / (chain.get("fps") or 24))
        if rate and nchar and dur:
            need = nchar / rate
            if need > dur:
                rep.error("WF-20",
                          f"镜头 {shot.get('id')} 只有 {dur:.2f}s，"
                          f"装不下 {nchar} 字语音（需 {need:.2f}s @{rate} 字/秒）",
                          fix="加长这一镜、拆镜，或回戏层砍字；不许把台词删掉")
            elif need > dur * 0.75:
                rep.warn("WF-20",
                         f"镜头 {shot.get('id')} 语音密度 {need / dur:.0%}"
                         f"（{nchar} 字 / {dur:.2f}s），超过戏 §三 自定的 75% 上限")

    # ── WF-10 取景必须写在描述段起始（旧线 5.11：首帧是什么构图第一句就写什么）──
    # 判据：`[Shot 1]` 标记之后紧接着就应该是取景句 —— 这是本项目四镜的写法，
    # 也正好把前面那一段画风句与 GEO 块排除在外，不会因为锁定件长而误报。
    if shot is not None:
        want = norm_ws(shot.get("framing_en") or shot.get("shot_size") or "")
        m = re.search(r"\[\s*shot\s*1\s*\]", styled, re.I)
        if m:
            head = norm_ws(styled[m.end():m.end() + 400])
            where = "`[Shot 1]` 之后 400 字内"
        else:
            probe = np_styled
            if pos is not None and pos >= 0 and style_len:
                probe = probe[:pos] + probe[pos + style_len:]
            if geo:
                probe = probe.replace(norm_ws(geo), "")
            head, where = probe.strip()[:300], "描述段开头 300 字内"
        if want and want.lower() not in head.lower():
            rep.error("WF-10",
                      f"镜头 {shot.get('id')} 的取景句「{want}」没出现在{where}",
                      got=head[:160] + "…",
                      fix="首帧与提示词取景不一致时 H3 会真的移机位，"
                          "并在背景留下一个重复的人")

    # ── WF-11 帧数 17k+5 ──
    if h3:
        wv = h3[0].get("widgets_values") or []
        if len(wv) >= 4 and isinstance(wv[3], int):
            n = wv[3]
            if n < 5 or (n - 5) % H3_GRID != 0:
                rep.error("WF-11", f"H3 帧数 {n} 不在 17k+5 网格上",
                          nearest=[(n - 5) // H3_GRID * H3_GRID + 5,
                                   ((n - 5) // H3_GRID + 1) * H3_GRID + 5])
            if shot is not None and shot.get("frames") and n != shot["frames"]:
                rep.error("WF-11",
                          f"工作流帧数 {n} ≠ 分镜表登记的 {shot['frames']}",
                          fix="分镜表是权威；改表或改工作流，不许两边不一致")
        else:
            rep.warn("WF-11", "H3 节点的 widgets_values 布局与预期不同，帧数检查跳过")

    # ── WF-12 画布 ──
    want_canvas = rules.get("canvas")
    canvas = None
    if h3:
        wv = h3[0].get("widgets_values") or []
        if len(wv) >= 3 and isinstance(wv[1], int) and isinstance(wv[2], int):
            canvas = (wv[1], wv[2])
    if canvas is None and lat:
        wv = lat[0].get("widgets_values") or []
        if len(wv) >= 2 and isinstance(wv[0], int) and isinstance(wv[1], int):
            canvas = (wv[0], wv[1])
    if canvas is None:
        # edit 链没有尺寸节点 —— 尺寸来自喂进去的那张底图，去读它的文件头
        for n in nodes:
            if n.get("type") != "LoadImage":
                continue
            name = (n.get("widgets_values") or [""])[0]
            for cand in (proj / "storyboard" / name, proj / "assets" / name,
                         proj / "outputs" / name):
                if cand.exists():
                    canvas = image_size(cand)
                    if canvas:
                        rep.info("WF-12", f"画布取自底图 {name}：{canvas[0]}×{canvas[1]}")
                    break
            if canvas:
                break
    if canvas:
        w, h_ = canvas
        if w % 32 or h_ % 32:
            rep.error("WF-12", f"画布 {w}×{h_} 不是 32 的倍数")
        # 项目锁定只在**镜头工作流**上强制：资产卡（768×1152 等）另有自己的画布，
        # 拿成片画布去判它们是误报（子 agent 2026-09-21：4 条）。
        # 需要单独指派的，登记在 audit_rules.json 的 canvas_by_workflow。
        want = (rules.get("canvas_by_workflow") or {}).get(wf_name) or want_canvas
        if want and is_shot_wf and list(canvas) != list(want):
            rep.error("WF-12", f"画布 {w}×{h_} ≠ 项目锁定 {want[0]}×{want[1]}")
        if kind == "h3" and min(w, h_) != H3_SHORT_SIDE:
            rep.error("WF-12", f"H3 画布短边 {min(w, h_)} ≠ {H3_SHORT_SIDE}")

    # ── WF-13 提示词里的书名号会被画进画面（旧线实测）──
    for ch in ("《", "》", "「", "」", "<", ">"):
        if ch in ("<", ">"):
            continue
        if ch in prompt:
            rep.error("WF-13", f"提示词里出现 `{ch}` —— 旧线实测会被画进画面")
            break

    # ── WF-14 防跳轴句（**只在没登记 GEO 块时兜底**，且只对镜头工作流）──
    anchor = rules.get("axis_sentence")
    if anchor and is_shot_wf and not geo and norm_ws(anchor).lower() not in norm_ws(prompt).lower():
        rep.error("WF-14", "缺防跳轴句（GEO 的 screen direction rule 必须逐字在提示词里）",
                  expect=anchor[:90] + "…")

    # ── WF-15 采样档位与 LoRA 必须成对 ──
    lora_steps = []
    for n in nodes:
        if n.get("type") != "LoraLoaderModelOnly":
            continue
        name = (n.get("widgets_values") or [""])[0] or ""
        m = re.search(r"(\d+)\s*steps?", name)
        if m:
            lora_steps.append(int(m.group(1)))
    used = []
    for n in nodes:
        t = n.get("type")
        wv = n.get("widgets_values") or []
        if t in ("BasicScheduler",) and len(wv) >= 2 and isinstance(wv[1], int):
            used.append(wv[1])
        elif t == "KSampler" and len(wv) >= 3 and isinstance(wv[2], int):
            used.append(wv[2])
    if lora_steps and used and set(lora_steps) != set(used):
        rep.error("WF-15", f"采样步数 {sorted(set(used))} 与 LoRA 档位 {sorted(set(lora_steps))} 不成对",
                  fix="Ref2VA 只有 4 步 LoRA；8 步是 fl2v 的")

    # ── WF-16 工作流自洽：SaveVideo 前缀 / LoadImage 必须与镜头表登记的一致 ──
    # 一个工作流文件被反复改写成四镜，最容易留下的就是这种"串档"。
    if shot is not None:
        sv = next((n for n in nodes if n.get("type") == "SaveVideo"), None)
        if sv:
            prefix = (sv.get("widgets_values") or [""])[0] or ""
            sid = shot.get("id")
            if sid and not re.search(rf"(^|[/_]){re.escape(sid)}(_|$)", prefix):
                rep.error("WF-16",
                          f"SaveVideo 前缀 `{prefix}` 里没有镜头号 {sid}",
                          fix="一镜一条工作流，不许反复改写同一个文件")
        li = next((n for n in nodes if n.get("type") == "LoadImage"), None)
        if li:
            got = (li.get("widgets_values") or [""])[0]
            want = shot.get("first_frame")
            if want and got and got != want:
                rep.error("WF-16",
                          f"LoadImage 用的是 `{got}`，镜头表登记的首帧是 `{want}`")

    # ── WF-18 提示词必须另存一份纯文本（规矩 §1 的 `prompts/` 层）──
    # 2026-09-21 的实情：`prompts/` 是**空的**，提示词只活在工作流 JSON 里。
    # 后果是致命的 —— 四镜共用一个工作流反复改写，S02 的提示词被覆盖后**无处可寻**，
    # 既不能 diff、也不能复盘"当时到底发了什么"。
    if shot is not None:
        sid = shot.get("id")
        pf = proj / "prompts" / f"{sid}.prompt.md"
        if sid and not pf.exists():
            rep.error("WF-18",
                      f"提示词没有以纯文本归档：prompts/{sid}.prompt.md",
                      fix="跑 `python tools/pipeline_audit.py sync-prompts <项目>` 生成。"
                          "它是工作流被改写时唯一的备份，也让前后两版可以 diff")
        elif sid and norm_ws(read(pf)) != norm_ws(prompt):
            rep.error("WF-18",
                      f"prompts/{sid}.prompt.md 与工作流里的提示词**不一致**（有一边被改过）",
                      fix="两边必须一致；改哪边都要同步另一边，否则审计的是旧版")

    packet = {
        "project": proj.name,
        "subject": wf_name,
        "kind": kind,
        "workflow_file": f"workflows/{wf_name}.json",
        "prompt_chars": noscript_chars(prompt),
        "prompt": prompt,
        "shot": shot,
        "beats_owned": [
            {"id": b, "header": (chain.get("beats") or {}).get(b, {}).get("header", ""),
             "dialogue": (chain.get("beats") or {}).get(b, {}).get("channels", {}).get("对白", []),
             "vo": (chain.get("beats") or {}).get(b, {}).get("channels", {}).get("VO", []),
             "visual": (chain.get("beats") or {}).get(b, {}).get("channels", {}).get("画面", [])}
            for b in (shot or {}).get("beats", [])],
        "geo_block": geo,
        "mechanical": rep.dump(),
    }
    return rep, packet


# ══════════════════════════════════════════════════════════════════════
#  封条：把 agent 的判定钉在文件哈希上
# ══════════════════════════════════════════════════════════════════════
def subject_files(proj: Path, subject: str, rules: dict) -> dict:
    """被审对象 → {相对路径: 绝对路径}。**改了其中任何一个，封条立即过期。**"""
    out = {}
    if subject in ("postflight", "chain"):
        for rel in (rules.get("script"), rules.get("geo_file"),
                    rules.get("shot_table"), "项目卡.md",
                    "storyboard/画幅1376x768_光学参数.md"):
            if rel and (proj / rel).exists():
                out[rel] = proj / rel
        for p in sorted((proj / "workflows").glob("*.json")):
            out[str(p.relative_to(proj))] = p
        out["audit_rules.json"] = proj / "audit_rules.json"
    else:
        p = proj / "workflows" / f"{subject}.json"
        if p.exists():
            out[str(p.relative_to(proj))] = p
        for rel in (rules.get("script"), rules.get("shot_table"), rules.get("geo_file")):
            if rel and (proj / rel).exists():
                out[rel] = proj / rel
        out["audit_rules.json"] = proj / "audit_rules.json"

        # ── SEAL-01：**首帧血缘与提示词归档也必须绑进封条**（子 agent 2026-09-21 实测的漏洞）──
        # 原先只绑 5 个文件，不含 `workflows/FF_*.json` ——
        # 于是**改了首帧提示词，这一镜的封条不会过期，verify 照样报"封条有效"**。
        # 而画风与身份恰恰是首帧那条工作流决定的（SHOT-05/06、WF-22、WF-07/08 说的都是它）。
        # "改了提示词就必须重新审"这条在首帧一侧原本是漏的。
        try:
            tbl = json.loads(read(proj / rules["shot_table"])) if rules.get("shot_table") else {}
        except (OSError, ValueError):
            tbl = {}
        for s in tbl.get("shots") or []:
            if s.get("workflow") != subject:
                continue
            fw = s.get("first_frame_workflow")
            if fw and (proj / "workflows" / f"{fw}.json").exists():
                out[f"workflows/{fw}.json"] = proj / "workflows" / f"{fw}.json"
            pf = proj / "prompts" / f"{s.get('id')}.prompt.md"
            if pf.exists():
                out[str(pf.relative_to(proj))] = pf
    return out


def audit_path(proj: Path, subject: str) -> Path:
    d = proj / "review" / "audits"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{subject}.audit.json"


def _chain_for(proj: Path, rules: dict, table_rel: str | None = None,
               materials: str = "error"):
    """取「当前场次」的层链。`table_rel` 不给就用项目级登记的那一份。"""
    return check_chain(proj, rules, materials=materials, table_rel=table_rel)


def _merge_reports(rep: Report, extra: Report, prefix: str = "") -> Report:
    """把一份子报告并进主报告（**保留原有 level**，不一律升成 ERROR）。"""
    for it in extra.items:
        msg = f"[{prefix}] {it['msg']}" if prefix else it["msg"]
        rep.add(it["level"], it["code"], msg,
                **{k: v for k, v in it.items() if k not in ("level", "code", "msg")})
    return rep


def cmd_preflight(proj: Path, wf_name: str, rules: dict, as_json: bool) -> int:
    # 多场次：先认这条工作流属于哪一场，用那一场的链 —— **不许拿别的场的镜头表去判它**
    rel = table_for_workflow(proj, rules, wf_name)
    crep, chain = _chain_for(proj, rules, rel)
    rep, packet = check_workflow(proj, wf_name, rules, chain)
    packet["chain"] = crep.dump()
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    pf = PACKET_DIR / f"{proj.name}.{wf_name}.packet.json"
    pf.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")

    if as_json:
        print(json.dumps({"chain": crep.dump(), "workflow": rep.dump(),
                          "packet": str(pf)}, ensure_ascii=False, indent=2))
    else:
        crep.print()
        rep.print()
        print(f"\n📦 审计包：{pf.relative_to(ROOT)}")
        print(f"   下一步：把审计包交给子 agent，它写出判定 JSON 后跑")
        print(f"   python tools/pipeline_audit.py seal {proj.name} {wf_name} <判定.json>")
    return 0 if (rep.ok() and crep.ok()) else 1


def cmd_packet(proj: Path, subject: str) -> int:
    pf = PACKET_DIR / f"{proj.name}.{subject}.packet.json"
    if not pf.exists():
        raise SystemExit(f"❌ 没有审计包 {pf} —— 先跑 preflight")
    print(read(pf))
    return 0


def cmd_seal(proj: Path, subject: str, verdict_file: str, rules: dict) -> int:
    vf = Path(verdict_file)
    if not vf.is_absolute():
        vf = ROOT / vf
    if not vf.exists():
        raise SystemExit(f"❌ 判定文件不存在：{vf}")
    v = json.loads(read(vf))

    for k in ("subject", "verdict", "findings"):
        if k not in v:
            raise SystemExit(f"❌ 判定 JSON 缺字段 `{k}`（schema 见 pipeline/docs/06_审计闸门.md）")
    if v["verdict"] not in ("pass", "fail"):
        raise SystemExit("❌ verdict 只能是 pass / fail")
    if v["subject"] not in (subject, f"{proj.name}/{subject}"):
        raise SystemExit(f"❌ 判定里的 subject={v['subject']!r} 与要封存的 {subject!r} 对不上")

    # 机械 ERROR 必须逐条被 agent 处理：要么列进 findings，要么显式豁免并给理由
    #
    # ⚠️ **只算这一条工作流自己的错。** `check_chain` 报的是**项目级**问题
    # （BEAT-01 节拍没人认领、SHOT-01 别的镜缺字段…），拿它去拦单条工作流的封条是错的 ——
    # 那样连画风探针都封不了（2026-09-21 实测：STYLE_I 自身 ERROR 0，却被 13 条链错误拦住）。
    # 例外：链上的错**点名了这条工作流**（`SHOT-05 …出自 FF_EP02SC01_shot`、
    # `SHOT-06 首帧工作流 X 被 4 镜共用`）→ 那确实是它的错，要拦。
    pf = PACKET_DIR / f"{proj.name}.{subject}.packet.json"
    mech_errors = []
    if pf.exists():
        pk = json.loads(read(pf))
        mech_errors = list((pk.get("mechanical") or {}).get("errors") or [])
        mech_errors += [e for e in ((pk.get("chain") or {}).get("errors") or [])
                        if subject in str(e.get("msg", ""))]
    waived = {w.get("code") for w in (v.get("waivers") or [])}
    if not all(w.get("reason") for w in (v.get("waivers") or [])):
        raise SystemExit("❌ 每条 waiver 都必须写 reason")
    unhandled = [e for e in mech_errors if e["code"] not in waived]
    if v["verdict"] == "pass" and unhandled:
        raise SystemExit(
            "❌ 机械检查还有 " + str(len(unhandled)) + " 条 ERROR，不能判 pass：\n  " +
            "\n  ".join(f"[{e['code']}] {e['msg'][:90]}" for e in unhandled) +
            "\n要么修，要么在 waivers 里逐条给理由。")

    files = subject_files(proj, subject, rules)
    v["subjects"] = {rel: sha256(p) for rel, p in files.items()}
    v["sealed_at"] = datetime.now().isoformat(timespec="seconds")
    v["sealed_by"] = "tools/pipeline_audit.py seal"
    if pf.exists():
        v["packet"] = str(pf.relative_to(ROOT))
        v["mechanical_at_seal"] = {"errors": len(mech_errors)}
    out = audit_path(proj, subject)
    out.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🔒 已封存 {out.relative_to(ROOT)}（绑定 {len(files)} 个文件）")
    print(f"   判定：{v['verdict']}　findings：{len(v['findings'])}")
    return 0 if v["verdict"] == "pass" else 1


def cmd_verify(proj: Path, subject: str, rules: dict, quiet: bool = False) -> int:
    """run.py 提交前调它。0=放行，1=判定不过，2=封条缺失/过期。"""
    out = audit_path(proj, subject)
    if not out.exists():
        print(f"⛔ [AUDIT-01] 没有审计封条 {out.relative_to(ROOT)}。")
        print(f"   先跑：python tools/pipeline_audit.py preflight {proj.name} {subject}")
        print(f"   再让子 agent 出判定，然后 seal。")
        return 2
    v = json.loads(read(out))
    files = subject_files(proj, subject, rules)
    stale = []
    for rel, h in (v.get("subjects") or {}).items():
        p = proj / rel
        if not p.exists() or sha256(p) != h:
            stale.append(rel)
    for rel in files:
        if rel not in (v.get("subjects") or {}):
            stale.append(rel + "（新增，未在封条内）")
    if stale:
        print(f"⛔ [AUDIT-02] 审计封条已过期 —— 被审文件在审计之后变了：{stale}")
        print(f"   提示词改了就必须重新审。重跑 preflight → 子 agent → seal。")
        return 2
    if v["verdict"] != "pass":
        blocking = v.get("blocking") or [f.get("id") for f in v["findings"]
                                         if f.get("level") == "error"]
        print(f"⛔ [AUDIT-03] 审计判定为 fail。阻塞项：{blocking}")
        for f in v["findings"]:
            if f.get("level") == "error":
                print(f"   - [{f.get('id','?')}] {f.get('claim','')[:160]}")
        return 1
    if not quiet:
        print(f"🔓 审计封条有效（{v.get('sealed_at')}，{len(v.get('subjects') or {})} 个文件），"
              f"判定 pass，findings {len(v['findings'])} 条")
    return 0


# ══════════════════════════════════════════════════════════════════════
#  第三道：项目完成后的**流程**审计
# ══════════════════════════════════════════════════════════════════════
def cmd_postflight(proj: Path, rules: dict, as_json: bool) -> int:
    # ⚠️ **多场次：逐场次各跑一遍链，再合并。**
    # 只跑项目级那一份的话，第二个场次的镜头表**根本不会被审计** ——
    # 那是"检查器没跑到"，比报错更危险（规矩 §5.C 第 12 条同理）。
    crep = Report(f"层链与节拍覆盖 · {proj.name}（全 {len(all_shot_tables(proj, rules))} 场）")
    chain: dict = {"beats": {}, "shots": [], "fps": 24, "total_frames": 0, "tables": []}
    for rel in all_shot_tables(proj, rules):
        one, ch = check_chain(proj, rules, table_rel=rel)
        _merge_reports(crep, one, prefix=Path(rel).stem)
        chain["beats"].update(ch.get("beats") or {})
        chain["shots"].extend(ch.get("shots") or [])
        chain["total_frames"] += int(ch.get("total_frames") or 0)
        if ch.get("table"):
            chain["tables"].append(ch["table"])
    per_wf = []
    for wf in sorted((proj / "workflows").glob("*.json")):
        r, _pk = check_workflow(proj, wf.stem, rules, chain)
        a = audit_path(proj, wf.stem)
        sealed = json.loads(read(a)) if a.exists() else None
        per_wf.append({
            "workflow": wf.stem,
            "errors": [i["code"] for i in r.errors],
            "warns": [i["code"] for i in r.warns],
            "sealed": None if sealed is None else {
                "verdict": sealed.get("verdict"),
                "sealed_at": sealed.get("sealed_at"),
                "findings": len(sealed.get("findings") or [])},
        })
    artifacts = sorted(str(p.relative_to(proj))
                       for p in (proj / "outputs").glob("*") if p.is_file())
    packet = {
        "project": proj.name,
        "kind": "postflight",
        "chain": crep.dump(),
        "beats": chain.get("beats") or {},
        "shots": chain.get("shots") or [],
        "workflows": per_wf,
        "artifacts": artifacts,
        "questions": [
            "本轮流程里，哪一步**本该拦住**某个缺陷却没有拦住？",
            "哪些缺陷本程序已经能机械抓到？哪些只能靠人/agent 的语义判断？",
            "为了下一轮不再犯，**要新增哪一条机械检查**？（写成可实现的判据）",
            "有没有'检查器误报'或'检查器过期'的迹象？",
        ],
    }
    PACKET_DIR.mkdir(parents=True, exist_ok=True)
    pf = PACKET_DIR / f"{proj.name}.postflight.packet.json"
    pf.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    if as_json:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    else:
        crep.print()
        print(f"\n📦 流程审计包：{pf.relative_to(ROOT)}（{len(per_wf)} 条工作流，"
              f"{len(artifacts)} 个产物）")
    return 0 if crep.ok() else 1


def cmd_status(proj: Path, rules: dict) -> int:
    # 多场次：逐场次跑链
    crep = Report(f"层链与节拍覆盖 · {proj.name}（全 {len(all_shot_tables(proj, rules))} 场）")
    for rel in all_shot_tables(proj, rules):
        one, _ch = check_chain(proj, rules, table_rel=rel)
        _merge_reports(crep, one, prefix=Path(rel).stem)
    crep.print()
    print("\n审计封条：")
    d = proj / "review" / "audits"
    # ⚠️ 只认 `*.audit.json` —— 同目录下的 `*.verdict.json` 是 agent 写的判定，
    # 不是封条，拿它去 verify 会报一堆假的 AUDIT-01。
    seals = sorted(d.glob("*.audit.json")) if d.exists() else []
    if not seals:
        print("  （一条都没有）")
    for f in seals:
        sub = f.name[: -len(".audit.json")]
        v = json.loads(read(f))
        rc = cmd_verify(proj, sub, rules, quiet=True)
        state = {0: "✅ 有效 pass", 1: "❌ 判定 fail", 2: "⌛ 缺失/过期"}[rc]
        print(f"  - {sub:<28} {state}   sealed {v.get('sealed_at','?')}")
    return 0


def cmd_sync_prompts(proj: Path, rules: dict) -> int:
    """把每条工作流里的正向提示词抽成 `prompts/<镜头号>.prompt.md`。

    **这是派生物，不做任何内容决定** —— 纯粹把已经存在的工作流里的文本复制出来，
    让 `prompts/` 这一层真正落地（规矩 §1），也让提示词能被 diff、能在工作流被改写后幸存。
    """
    # ⚠️ 多场次：逐场次抽 —— 只抽项目级那一份的话，别的场次的提示词**根本不会落地**
    d = proj / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    written, missing = [], []
    for rel_tbl in all_shot_tables(proj, rules):
        _rep, chain = check_chain(proj, rules, table_rel=rel_tbl)
        for s in chain.get("shots") or []:
            sid, wfn = s.get("id"), s.get("workflow")
            if not sid:
                continue
            if not wfn or not (proj / "workflows" / f"{wfn}.json").exists():
                missing.append(f"{sid}（工作流文件不存在，提示词已丢失）")
                continue
            wf = load_workflow(proj / "workflows" / f"{wfn}.json")
            h3 = h3_nodes(wf)
            if h3:
                prompt = (h3[0].get("widgets_values") or [""])[0] or ""
            else:
                sampler = next((n for n in wf.get("nodes", []) if n.get("type") in
                                ("KSampler", "KSamplerAdvanced", "SamplerCustom",
                                 "SamplerCustomAdvanced")), None)
                prompt = upstream_text(wf, sampler["id"], "positive") if sampler else ""
            if not prompt.strip():
                missing.append(f"{sid}（取不到正向提示词）")
                continue
            f = d / f"{sid}.prompt.md"
            old = read(f) if f.exists() else None
            f.write_text(prompt, encoding="utf-8")
            written.append(f"{sid} ← workflows/{wfn}.json" +
                           ("（覆盖了旧版）" if old is not None else ""))
    print(f"✅ 已同步 {len(written)} 份提示词到 {d.relative_to(proj)}：")
    for w in written:
        print(f"   - {w}")
    if missing:
        print(f"⚠️  {len(missing)} 镜无法同步：")
        for m in missing:
            print(f"   - {m}")
    return 0 if not missing else 1


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="流程审计闸门（规矩 §7）")
    ap.add_argument("cmd", choices=["chain", "preflight", "packet", "seal",
                                    "verify", "postflight", "status", "sync-prompts"])
    ap.add_argument("project")
    ap.add_argument("subject", nargs="?", help="工作流名 / postflight / chain")
    ap.add_argument("verdict", nargs="?", help="seal 用：判定 JSON 路径")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    proj = project_dir(a.project)
    rules = load_rules(proj)

    if a.cmd == "chain":
        # 多场次：逐场次报，**合并成一份结论**
        # ⚠️ `materials="pending"`：这条命令是**平时随便看**用的，
        # 「首帧／工作流还没产出」在这个时点不是错（那是 S2 登记时就要写下的东西）。
        # 一律报 ERROR 会让人以为"链坏了"，而真正该拦的时点是 S6/S8（推 GPU 之前）。
        # 要严格版（产物必须在）用 `pipeline.py gate <项目> S6`。
        tables = all_shot_tables(proj, rules)
        rep = Report(f"层链与节拍覆盖 · {proj.name}（全 {len(tables)} 场）")
        merged: dict = {"beats": {}, "shots": [], "tables": []}
        for rel in tables:
            one, ch = check_chain(proj, rules, materials="pending", table_rel=rel)
            _merge_reports(rep, one, prefix=Path(rel).stem)
            merged["beats"].update(ch.get("beats") or {})
            merged["shots"].extend(ch.get("shots") or [])
            merged["tables"].append(rel)
        chain = merged
        if a.json:
            print(json.dumps({"report": rep.dump(), "beats": chain.get("beats"),
                              "shots": chain.get("shots"),
                              "tables": chain.get("tables")},
                             ensure_ascii=False, indent=2))
        else:
            rep.print()
        return 0 if rep.ok() else 1
    if a.cmd == "preflight":
        if not a.subject:
            ap.error("preflight 需要工作流名")
        return cmd_preflight(proj, a.subject, rules, a.json)
    if a.cmd == "packet":
        if not a.subject:
            ap.error("packet 需要主题")
        return cmd_packet(proj, a.subject)
    if a.cmd == "seal":
        if not a.subject or not a.verdict:
            ap.error("seal 需要：<主题> <判定.json>")
        return cmd_seal(proj, a.subject, a.verdict, rules)
    if a.cmd == "verify":
        if not a.subject:
            ap.error("verify 需要工作流名")
        return cmd_verify(proj, a.subject, rules)
    if a.cmd == "postflight":
        return cmd_postflight(proj, rules, a.json)
    if a.cmd == "status":
        return cmd_status(proj, rules)
    if a.cmd == "sync-prompts":
        return cmd_sync_prompts(proj, rules)
    return 0


if __name__ == "__main__":
    sys.exit(main())
