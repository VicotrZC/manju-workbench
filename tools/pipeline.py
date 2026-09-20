#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""漫剧制作管线 —— **阶段状态机 + 程序兜底**（规矩.md §2 的编排层）。

    python tools/pipeline.py stages   <项目>                  # 管线全景（文本）
    python tools/pipeline.py scenes   <项目>                  # 列出可选的「集/场」
    python tools/pipeline.py status   <项目> [--scene SCN01]  # 逐阶段状态 + 门禁
    python tools/pipeline.py gate     <项目> <阶段> [--scene] # 只跑某一个阶段的门禁
    python tools/pipeline.py verify   <项目> [--scene]        # **从零重跑全部门禁**
    python tools/pipeline.py brief    <项目> <阶段> [--scene] # 该阶段交给 agent 的作业单
    python tools/pipeline.py seal     <项目> <阶段> <判定.json> [--scene]
    python tools/pipeline.py ui       <项目> [--port 8788]    # 可视化界面

## 这个文件解决什么

用户 2026-09-21 的原话：**「要让程序兜底，不然大模型可能存在遗忘审计、忽略纠错」**。

所以本文件**不替 agent 做创作**，它只做三件事：

1. **把管线切成不可跳过的阶段**，每个阶段有明确的「输入齐了吗 / 产出齐了吗 / 门禁过了吗」。
2. **每个阶段推进前，现场重跑门禁** —— 不读缓存、不信上次的结论、不信 agent 说"我改好了"。
   状态是**每次算出来的**，不是存下来的。
3. **agent 步骤必须留判定并被哈希绑定**（复用 `tools/pipeline_audit.py` 的封条机制）——
   agent 忘了审、审了旧版、或者绕过，程序都拦得住。

## 分工（谁干什么）

| 执行者 | 干什么 | 谁兜底 |
|---|---|---|
| `prog` | 机械检查、格式校验、提交生成、产物合规 | 自己 |
| `agent` | 创作与语义判断（写分镜、抽资产、写提示词、审提示词、看图） | **程序校验它的产出** ＋ 封条 |
| `user` | 审美判断、花钱、破坏性操作（`规矩.md` §6） | —— |

**agent 报"通过" ≠ 内容合格**（规矩 §5.C 第 12 条）。本文件只保证：**该它看的它看了、
该它交的它交了、交了之后东西没被偷改。**
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ⚠️ **不要在这里重新包一层 `io.TextIOWrapper(sys.stdout.buffer)`**。
# `pipeline_audit` 在 import 时已经包过一次；再包一层会让第一次包的对象被回收并
# **关掉底层 buffer**，报 `ValueError: I/O operation on closed file`（实测踩到）。
# 用 `reconfigure` 改编码即可，不新建对象。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import pipeline_audit as PA  # noqa: E402  —— 复用同一套检查与封条，不另写一份


# ══════════════════════════════════════════════════════════════════════
#  阶段定义
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Stage:
    id: str
    name: str
    executor: str                 # prog | agent | user
    why: str                      # 这一阶段为什么存在（一句话）
    produces: list[str] = field(default_factory=list)   # 产出（相对项目根）
    methods: list[str] = field(default_factory=list)    # agent 该先读哪些方法文件
    seal_required: bool = False   # agent 步骤是否必须留封条
    blocks_gpu: bool = False      # 不过这一关不许碰 GPU
    depends: list[str] = field(default_factory=list)


#: **顺序即依赖**：后面的阶段一律不许跳过前面的。
STAGES: list[Stage] = [
    Stage(
        id="S0", name="选题（项目／集／场）", executor="user",
        why="一切下游工作的输入。选错场次，后面全废。",
        produces=["<scene> 的镜头表或戏文件存在"],
        depends=[],
    ),
    Stage(
        id="S1", name="剧本（场次＋节拍流）", executor="agent",
        why="戏是节拍的唯一权威；分镜只能认领，不能新增（pipeline/docs/02 规则七）。",
        produces=["script/*_戏.md"],
        methods=["pipeline/docs/02_工作规则.md", "story/大纲.md", "story/世界观.md"],
        depends=["S0"],
    ),
    Stage(
        id="S2", name="分镜（机器可读镜头表）", executor="agent",
        why="戏是散文，镜头表是**程序能核对的**东西。没有它，节拍被吞了也没人知道"
            "（买肉场 B1「骑车赶到菜市」就是这么整段消失的）。",
        produces=["storyboard/<场次>_镜头表.json"],
        methods=["storyboard/SCN01_GEO空间地图.md", "storyboard/画幅1376x768_光学参数.md",
                 "pipeline/docs/04_横屏焦距与景别反推表.md"],
        depends=["S1"],
    ),
    Stage(
        id="S3", name="验分镜", executor="prog",
        why="节拍覆盖 / 镜头表完整性 / 首帧血缘 —— 全部机械可判，不许靠人记得。",
        depends=["S2"],
    ),
    Stage(
        id="S4", name="抽离角色／道具／场景", executor="agent",
        why="资产先于分镜（01_资产规范 §〇 铁律：无图不进分镜）。"
            "清单必须机器可读，否则「资产有没有接进生成路径」无从核对 ——"
            "买肉场就是资产做完了、一镜都没用。",
        produces=["storyboard/<场次>_资产清单.json"],
        methods=["pipeline/docs/01_资产规范.md", "story/人物表.md"],
        depends=["S3"],
    ),
    Stage(
        id="S5", name="验资产", executor="prog",
        why="清单 schema / 编号规范 / 图是否真在盘上 / 是否被分镜引用。",
        depends=["S4"],
    ),
    Stage(
        id="S6", name="写提示词（含首帧工作流）", executor="agent",
        why="把上游每一样东西落进提示词。**首帧工作流与视频工作流分开、一镜一文件** ——"
            "买肉场四镜共用一个文件反复改写，S02 的提示词被覆盖后永远找不回来了。",
        produces=["workflows/*.json", "prompts/<镜号>.prompt.md"],
        methods=["h3res/guide_ref_en.md", "storyboard/SCN01_GEO空间地图.md",
                 "audit_rules.json"],
        depends=["S5"],
    ),
    Stage(
        id="S7", name="审查提示词（agent）", executor="agent",
        why="规矩 §7 子 agent 监督协议：跑 GPU 之前先让子 agent 逐拍核「这一拍到底进没进这条提示词」。"
            "**判定要封条**，改了提示词封条自动过期。",
        seal_required=True, blocks_gpu=True,
        methods=["pipeline/docs/06_审计闸门.md"],
        depends=["S6"],
    ),
    Stage(
        id="S8", name="连服务器生成", executor="prog",
        why="**没有有效封条就不许提交**（tools/run.py 已接成硬闸门）。",
        produces=["outputs/*.mp4", "outputs/*.png"],
        blocks_gpu=True,
        depends=["S7"],
    ),
    Stage(
        id="S9", name="按设定检查生成内容", executor="prog",
        why="尺寸／帧数／时长／音轨 vs 镜头表登记值；画面内容（乱码文字、景别、服装）"
            "机械判不了，交 agent 或用户，但**结论要落文件、要能复核**。",
        depends=["S8"],
    ),
    Stage(
        id="S10", name="流程审计（agent）", executor="agent",
        why="一个场次做完，让子 agent 审**流程本身**：哪一步本该拦住却没拦住，"
            "并把新检查写成可实现的判据。**这是管线自我更新的唯一入口。**",
        seal_required=True,
        methods=["pipeline/docs/06_审计闸门.md", "pipeline/docs/02_工作规则.md"],
        depends=["S9"],
    ),
]

STAGE_BY_ID = {s.id: s for s in STAGES}


#: **阶段 → 该掌握的外部方法**（2026-09-21 调研所得）。
#: 用户原话：「这些 skill 就是 agent 应该掌握并用来判断的方法」。
#: 它们是**判断依据**，不是可以直接抄进来的规矩 —— 抄之前先核 license 与来源
#: （`规矩.md` §9：上游转述过一手就可能变形）。
SKILL_MAP: dict[str, list[dict]] = {
    "S1": [
        {"src": "zenstory-ai/drama-skills（2082★ MIT）", "what":
            "`short-drama-write`：单集目标／因果节拍／可拍剧本；`short-drama-novel-analyze`：原著抽样快评与分集候选"},
        {"src": "eternityspring/shuohao-skills（3615★ Apache-2.0）", "what":
            "`novel-script`：场次＋节拍流，逐集时长按语速确定性折算，台词本按角色聚合带音色提示词"},
    ],
    "S2": [
        {"src": "shuohao-skills", "what":
            "`novel-storyboard`：段（一次生成 ≤15 秒）→ 分镜（2–5 秒硬门）→ 分镜图（主图钉 0.00 秒、子图钉各自切点）"},
        {"src": "zenstory drama-skills", "what":
            "`short-drama-storyboard`：场次视觉计划与 Coverage、原文落实、镜头、边界与冻结关键帧"},
        {"src": "Shanyin-ai/shanyin-director-master（537★）", "what":
            "导演定调 → 节奏规划 → 标准九列分镜表（xlsx）"},
    ],
    "S4": [
        {"src": "pipeline/docs/01_资产规范.md（本地权威）", "what": "五视图 / 签名标记 / 砍头比例"},
        {"src": "khanhhuyenngo985-sys/character-scene-design-skills（12★）", "what":
            "身高比例锁、三视图一致性、道具锚点、场景动线 —— 星数低，只作参考"},
    ],
    "S6": [
        {"src": "zenstory drama-skills · `skills/short-drama-video-prompts/references/minimax-h3.md`",
         "what": "**H3 方言**：说话人绑定 `(S1)`、`<d>[Language] …</d>`、`<scenetrans>` 跨镜对白、"
                 "`<cutoff>`、对白估时（**它说中文约 4.1 可发声字/秒**，与我们戏 §三 的 5.50 冲突，未定）"},
        {"src": "Cicaba/minimax-h3-prompts（0★）", "what":
            "中文优先、保留官方英文字段名的写法；联系表/分镜网格的**泄漏防护**（防九宫格混进成片）"},
        {"src": "AIMixer/ComfyUI_MiniMaxH3_Director（1862★）", "what":
            "r2v 公共参数（角色锁定 / subject_definitions）＋ 每组图片1–9；段间引导上下文帧数 5/22/39/56；默认 25 步"},
    ],
    "S8": [
        {"src": "tools/run.py（唯一执行器）", "what": "提交前强制 `check_before_gpu` ＋ 审计封条"},
    ],
    "S9": [
        {"src": "zenstory drama-skills · `creator_markdown_check.py`", "what":
            "跨文档引用核对，**报原因而不是「校验失败」**；连续性锁 `LOCK-` 要能原样贴进提示词"},
        {"src": "A-cat-with-carrots/OnlyShot（283★）", "what": "17 条失败模式清单，当审查对照表"},
    ],
    "S10": [
        {"src": "pipeline/docs/06_审计闸门.md", "what": "封条机制与检查码表"},
        {"src": "jlam00-dev/hardcore-director（12★）", "what":
            "它的「质量门禁」清单（站位/朝向/距离/受力/落点、伤痕连续性、时长之和=总时长、"
            "区分观察与推断）—— 和我们这套是同一思路，用来对表；星数低，别当权威"},
    ],
}


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig", errors="replace")


def project_dir(name: str) -> Path:
    return PA.project_dir(name)


def state_path(proj: Path) -> Path:
    return proj / "pipeline_state.json"


def load_state(proj: Path) -> dict:
    p = state_path(proj)
    if not p.exists():
        return {"_note": "本文件由 tools/pipeline.py 维护。**阶段状态不存这里** —— "
                         "状态是每次现场算出来的；这里只存 agent 的判定与说明。",
                "scenes": {}}
    return json.loads(read(p))


def save_state(proj: Path, st: dict):
    st["updated"] = datetime.now().isoformat(timespec="seconds")
    state_path(proj).write_text(json.dumps(st, ensure_ascii=False, indent=2),
                                encoding="utf-8")


def _quiet_verify(proj: Path, subject: str, rules: dict) -> int:
    """跑 audit 的封条校验，但**把它自己的打印吞掉** —— 否则一条 gate 会把
    十几行 AUDIT-* 原始输出倒进管线视图里（实测）。返回值才是我们要的。"""
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return PA.cmd_verify(proj, subject, rules, quiet=True)


class Rep:
    """门禁结果。ERROR = 卡住，WARN = 提示。"""
    def __init__(self, stage: str):
        self.stage = stage
        self.items: list[dict] = []

    def e(self, code, msg, **kw):
        self.items.append({"level": "ERROR", "code": code, "msg": msg, **kw})

    def w(self, code, msg, **kw):
        self.items.append({"level": "WARN", "code": code, "msg": msg, **kw})

    def i(self, code, msg, **kw):
        self.items.append({"level": "INFO", "code": code, "msg": msg, **kw})

    @property
    def errors(self):
        return [x for x in self.items if x["level"] == "ERROR"]

    @property
    def warns(self):
        return [x for x in self.items if x["level"] == "WARN"]

    def ok(self):
        return not self.errors

    def dump(self):
        return {"stage": self.stage, "ok": self.ok(),
                "errors": len(self.errors), "warns": len(self.warns),
                "items": self.items}


# ══════════════════════════════════════════════════════════════════════
#  场次发现
# ══════════════════════════════════════════════════════════════════════
def find_scenes(proj: Path, rules: dict) -> list[dict]:
    """一个「场次」= 一份机器可读镜头表。没有镜头表的场次**不算可选**。"""
    out = []
    for f in sorted((proj / "storyboard").glob("*_镜头表.json")):
        try:
            t = json.loads(read(f))
        except ValueError as exc:
            out.append({"id": f.stem, "bad": str(exc), "file": str(f.relative_to(proj))})
            continue
        shots = t.get("shots") or []
        out.append({
            "id": t.get("scene") or f.stem,
            "name": t.get("scene_name", ""),
            "episode": t.get("episode", ""),
            "file": str(f.relative_to(proj)),
            "shots": len(shots),
            "frames": sum(int(s.get("frames") or 0) for s in shots),
            "fps": t.get("fps") or 24,
            "workflows": [s.get("workflow") for s in shots if s.get("workflow")],
            "t": t,
        })
    return out


def pick_scene(proj: Path, rules: dict, scene_id: str | None):
    scenes = find_scenes(proj, rules)
    if not scenes:
        raise SystemExit(f"❌ {proj.name} 下没有 storyboard/*_镜头表.json —— 一个场次都没有，"
                         f"先走 S1/S2")
    if scene_id is None:
        return scenes[0]
    for s in scenes:
        if s["id"] == scene_id or s["file"] == scene_id:
            return s
    raise SystemExit(f"❌ 没有这个场次：{scene_id}\n现有：{[s['id'] for s in scenes]}")


# ══════════════════════════════════════════════════════════════════════
#  门禁（每个阶段一个；**都是现场跑的**）
# ══════════════════════════════════════════════════════════════════════
def gate_S0(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S0")
    r.i("S0-OK", f"当前单位：{scene['id']}（{scene.get('name','')}）"
                 f"　{scene['shots']} 镜 / {scene['frames']} 帧 / "
                 f"{scene['frames']/scene['fps']:.2f} 秒")
    return r


def gate_S1(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S1")
    rel = rules.get("script")
    f = proj / rel if rel else None
    if not f or not f.exists():
        r.e("S1-01", f"剧本层文件不在：{rel}",
            fix="这一场没有戏就没有节拍，后面全部无从核对")
        return r
    beats = PA.parse_script(f)
    if not beats:
        r.e("S1-02", f"从 {rel} 里解析不出任何节拍（`**B1 ｜ …**` 格式）",
            fix="戏必须写成九拍表，程序才认得出节拍")
        return r
    no_ch = [b for b, v in beats.items()
             if not any(v["channels"].values())]
    if no_ch:
        r.e("S1-03", f"这些节拍的五通道全是空的：{no_ch}")
    voiced = sum(1 for v in beats.values() if v["has_dialogue"] or v["has_vo"])
    r.i("S1-OK", f"解析出 {len(beats)} 个节拍，其中 {voiced} 个有语音"
                 f"（对白 {sum(v['dialogue_chars'] for v in beats.values())} 字 / "
                 f"VO {sum(v['vo_chars'] for v in beats.values())} 字）")
    return r


def gate_S2(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S2")
    t = scene.get("t") or {}
    shots = t.get("shots") or []
    if not shots:
        r.e("S2-01", "镜头表里没有镜头")
        return r
    for s in shots:
        for k in ("id", "beats", "shot_size", "lens_mm", "dist_m", "frames",
                  "first_frame", "workflow"):
            if not s.get(k):
                r.e("S2-02", f"镜头 {s.get('id')} 缺字段 `{k}`")
    r.i("S2-OK", f"{len(shots)} 镜登记齐")
    return r


def gate_S3(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """验分镜 = 直接复用审计程序的层链检查（只有一份判据，不抄第二份）。"""
    rep, chain = PA.check_chain(proj, rules)
    r = Rep("S3")
    for it in rep.items:
        if it["level"] == "INFO":
            continue
        (r.e if it["level"] == "ERROR" else r.w)(it["code"], it["msg"],
                                                 **{k: v for k, v in it.items()
                                                    if k not in ("level", "code", "msg")})
    if r.ok():
        r.i("S3-OK", "节拍覆盖 / 镜头表 / 首帧血缘 全部通过")
    return r


def gate_S4(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S4")
    f = proj / "storyboard" / f"{scene['id']}_资产清单.json"
    if not f.exists():
        r.e("S4-01", f"资产清单不在：storyboard/{scene['id']}_资产清单.json",
            fix="跑 `pipeline.py brief <项目> S4` 拿作业单交给 agent")
        return r
    try:
        m = json.loads(read(f))
    except ValueError as exc:
        r.e("S4-02", f"资产清单不是合法 JSON：{exc}")
        return r
    for key in ("characters", "props", "scenes"):
        if key not in m:
            r.e("S4-03", f"资产清单缺 `{key}` 段",
                fix="角色／道具／场景三段都要有，空的话写 []")
    ids = []
    for key in ("characters", "props", "scenes"):
        for a in (m.get(key) or []):
            if not a.get("id"):
                r.e("S4-04", f"{key} 里有条目没有 `id`")
                continue
            ids.append(a["id"])
            if not a.get("name"):
                r.w("S4-05", f"{a['id']} 没有 `name`")
    r.i("S4-OK", f"清单解析出 {len(ids)} 项资产：{'、'.join(ids)}")
    return r


def gate_S5(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S5")
    f = proj / "storyboard" / f"{scene['id']}_资产清单.json"
    if not f.exists():
        r.e("S5-01", "资产清单不在（S4 没过）")
        return r
    m = json.loads(read(f))
    shots_txt = json.dumps(scene.get("t") or {}, ensure_ascii=False)
    for key in ("characters", "props", "scenes"):
        for a in (m.get(key) or []):
            aid = a.get("id", "?")
            files = a.get("files") or []
            if not files:
                r.e("S5-02", f"{aid} 没有登记任何资产图文件",
                    fix="01_资产规范 §〇：无图不进分镜")
            for rel in files:
                if not (proj / "assets" / rel).exists() and \
                   not (proj / "outputs" / rel).exists():
                    r.e("S5-03", f"{aid} 的图不在盘上：{rel}")
            # **资产必须真的被这一场的镜头用上** —— 买肉场就是资产做完了、一镜没用
            if aid not in shots_txt:
                r.e("S5-04",
                    f"{aid} 在镜头表里**一次都没被引用** —— 做了资产却没用，"
                    f"成片和资产层脱钩",
                    fix="在镜头表里把该资产挂到用到它的镜头上；确实不用就删掉这一项")
    if r.ok():
        r.i("S5-OK", "清单 schema / 图在位 / 被分镜引用 全部通过")
    return r


def gate_S6(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """写提示词：每镜跑全套 WF-* 不变量。"""
    r = Rep("S6")
    _crep, chain = PA.check_chain(proj, rules)
    done = 0
    for s in (scene.get("t") or {}).get("shots") or []:
        wf = s.get("workflow")
        if not wf:
            r.e("S6-01", f"镜头 {s.get('id')} 没登记工作流文件")
            continue
        if not (proj / "workflows" / f"{wf}.json").exists():
            r.e("S6-02", f"镜头 {s.get('id')} 的工作流不存在：workflows/{wf}.json",
                fix="一镜一条工作流，不许反复改写同一个文件")
            continue
        sub, _pk = PA.check_workflow(proj, wf, rules, chain)
        for it in sub.errors:
            r.e(it["code"], f"[{s.get('id')}] {it['msg']}",
                **{k: v for k, v in it.items() if k not in ("level", "code", "msg")})
        done += 1
    if done and r.ok():
        r.i("S6-OK", f"{done} 条工作流的提示词不变量全部通过")
    return r


def gate_S7(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """审查提示词：**每镜必须有一条有效封条**。"""
    r = Rep("S7")
    for s in (scene.get("t") or {}).get("shots") or []:
        wf = s.get("workflow")
        if not wf:
            continue
        rc = _quiet_verify(proj, wf, rules)
        if rc == 0:
            continue
        why = {1: "判定 fail", 2: "封条缺失或已过期"}[rc]
        r.e("S7-01", f"镜头 {s.get('id')}（{wf}）的审计封条不过：{why}",
            fix=f"python tools/pipeline_audit.py preflight {proj.name} {wf}"
                f" → 子 agent 出判定 → seal")
    if r.ok():
        r.i("S7-OK", "每镜都有有效封条")
    return r


def gate_S8(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """生成：产物在不在、**是不是审计过的那一版生成的**。

    ⚠️ 只查"有没有产物"是不够的 —— 买肉场四镜的产物就是**在审计闸门存在之前**跑出来的，
    查存在性会显示"通过"，读起来像"生成没问题"。所以必须对时间：
    **产物必须晚于它那一条封条**，否则它不是被审过的那一版。
    """
    r = Rep("S8")
    for s in (scene.get("t") or {}).get("shots") or []:
        sid = s.get("id")
        wf = s.get("workflow")
        hits = [p for p in (proj / "outputs").glob(f"*{sid}*.mp4")] if sid else []
        if not hits:
            r.e("S8-01", f"镜头 {sid} 还没有产物（outputs/*{sid}*.mp4）",
                fix="过了 S7 的封条才能提交；提交走 tools/run.py")
            continue
        newest = max(p.stat().st_mtime for p in hits)
        seal = proj / "review" / "audits" / f"{wf}.audit.json" if wf else None
        if not seal or not seal.exists():
            r.e("S8-02", f"镜头 {sid} 有产物，但**这一镜没有任何审计封条** —— "
                         f"产物不是被审过的那一版生成的",
                fix="补审：preflight → 子 agent → seal")
        else:
            try:
                sv = json.loads(read(seal))
                sealed = datetime.fromisoformat(sv["sealed_at"]).timestamp()
                if newest < sealed:
                    r.e("S8-03",
                        f"镜头 {sid} 的产物（{datetime.fromtimestamp(newest):%m-%d %H:%M}）"
                        f"**早于封条**（{sv['sealed_at']}）—— 先生成后补审的",
                        fix="产物必须由审过的那一版生成；要么重跑，要么别把它当已审")
                else:
                    r.i("S8-OK", f"镜头 {sid} 产物晚于封条，来源可追")
            except (KeyError, ValueError):
                r.w("S8-04", f"镜头 {sid} 的封条读不出 sealed_at")
    return r


def gate_S9(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """按设定检查生成内容。

    机械部分**由 `pipeline.py qc` 产出**（自解 MP4 容器：画布／帧数／时长／帧率／音轨），
    语义部分（乱码文字／景别／服装／站位／音轨内容）机械判不了，**必须落成文件、必须有人看**。
    """
    r = Rep("S9")
    rec_path = proj / "review" / f"{scene['id']}_合规检查.json"
    if not rec_path.exists():
        r.e("S9-01", f"没有合规检查记录：review/{scene['id']}_合规检查.json",
            fix=f"先跑 `python tools/pipeline.py qc {proj.name} "
                f"--scene {scene['id']} --write` 把机械项填出来")
        return r
    try:
        q = json.loads(read(rec_path))
    except ValueError as exc:
        r.e("S9-02", f"合规检查记录不是合法 JSON：{exc}")
        return r

    # ① 记录是不是覆盖了当前这一版产物
    newest = 0.0
    for s in (scene.get("t") or {}).get("shots") or []:
        for p in (proj / "outputs").glob(f"*{s.get('id')}*.mp4"):
            newest = max(newest, p.stat().st_mtime)
    try:
        checked = datetime.fromisoformat(q["checked_at"]).timestamp()
        if newest and newest > checked + 1:
            r.e("S9-03", "合规检查记录**早于最新产物** —— 核的是旧版",
                fix="产物变过就重跑 qc")
    except (KeyError, ValueError):
        r.w("S9-04", "记录里读不出 checked_at，无法判断是否覆盖当前版本")

    # ② 机械项
    ms = q.get("machine_summary") or {}
    if ms.get("fail"):
        for c in (q.get("checks") or []):
            if c.get("result") == "fail":
                r.e("S9-05", f"{c.get('shot','')} 合规不过：{c.get('item')} —— "
                             f"期望 {c.get('expect')}，实测 {c.get('got')}",
                    detail=c.get("detail"))
    elif not ms:
        r.w("S9-06", "记录里没有 machine_summary（是老版本写的？重跑 qc）")

    # ③ 语义项 —— **不许静默通过**
    sem = [c for c in (q.get("checks") or []) if c.get("kind") == "semantic"]
    un = [c for c in sem if c.get("result") == "unchecked"]
    if un:
        r.w("S9-07", f"{len(un)} 条语义项还没人看："
                     f"{'、'.join(c['item'] for c in un)}",
            fix="画面文字／景别／服装／站位／音轨内容 —— 程序判不了，"
                "由 agent 或用户填进同一个文件")
    bad = [c for c in sem if c.get("result") == "fail"]
    for c in bad:
        r.e("S9-08", f"语义项不合规：{c['item']} —— {c.get('detail','')}")

    # ④ 感知类结论只有人能拍板（规矩 §5.C 第 11 条）
    if not q.get("verified_by_human"):
        r.w("S9-09", "合规结论还没有人看过（verified_by_human=false）—— "
                     "感知类结论只有用户能拍板")

    if r.ok():
        r.i("S9-OK", f"机械项 {ms.get('pass',0)} 条全过；语义项 "
                     f"{len(sem) - len(un)}/{len(sem)} 已填")
    return r


def gate_S10(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    r = Rep("S10")
    rc = _quiet_verify(proj, "postflight", rules)
    if rc == 2:
        r.e("S10-01", "还没有 postflight 流程审计封条",
            fix="python tools/pipeline_audit.py postflight <项目> → 子 agent 审 → seal")
    elif rc == 1:
        r.e("S10-02", "postflight 判定为 fail（见 review/audits/postflight.audit.json）")
    else:
        r.i("S10-OK", "流程审计封条有效")
    return r


GATES = {s.id: globals()[f"gate_{s.id}"] for s in STAGES}


# ══════════════════════════════════════════════════════════════════════
#  跑管线
# ══════════════════════════════════════════════════════════════════════
def scan(proj: Path, scene_id: str | None = None, only: str | None = None) -> dict:
    """**现场重跑全部门禁。** 状态不读缓存 —— 这是"程序兜底"的全部意思。

    ⚠️ **默认全跑，不做级联短路。** 短路只能看到第一个错，看不到全貌；
    而推进顺序本来就由门禁自己保证（S6 查工作流、S7 查封条、S8 查产物），
    不需要靠"前面没过就不看后面"来实现。
    """
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)
    state = load_state(proj)
    rows = []
    first_fail = None
    for st in STAGES:
        if only and st.id != only:
            continue
        rep = GATES[st.id](proj, rules, scene, state)
        ok = rep.ok()
        if not ok and first_fail is None:
            first_fail = st.id
        rows.append({"id": st.id, "name": st.name, "executor": st.executor,
                     "why": st.why, "status": "pass" if ok else "fail",
                     "report": rep.dump(), "artifacts": _artifacts(proj, scene, st),
                     "methods": st.methods, "seal_required": st.seal_required,
                     "blocks_gpu": st.blocks_gpu})
    # 下游标记：上面有没过的地方，这一步就"轮不到你"
    if not only:
        seen_fail = False
        for row in rows:
            if seen_fail:
                row["waiting_on"] = first_fail
            if row["status"] != "pass":
                seen_fail = True
    return {"project": proj.name, "scene": {k: v for k, v in scene.items() if k != "t"},
            "scene_raw": scene.get("t"), "stages": rows,
            "next_action": first_fail, "rules_file": "audit_rules.json",
            "checked_at": datetime.now().isoformat(timespec="seconds")}


def _artifacts(proj: Path, scene: dict, st: Stage) -> dict:
    out = {}
    cands = []
    if st.id in ("S1",):
        cands = [proj / "script"]
    elif st.id in ("S2", "S3", "S4", "S5"):
        cands = [proj / "storyboard"]
    elif st.id == "S6":
        cands = [proj / "workflows", proj / "prompts"]
    elif st.id in ("S8", "S9"):
        cands = [proj / "outputs"]
    for d in cands:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*")):
            if f.is_file() and f.suffix.lower() in (".json", ".md", ".txt", ".mp4", ".png"):
                if f.stat().st_size > 8_000_000:
                    out[str(f.relative_to(proj))] = f"{f.stat().st_size} B"
                else:
                    out[str(f.relative_to(proj))] = sha256(f)[:12]
    return out


def print_status(res: dict):
    icon = {"pass": "✅", "fail": "⛔"}
    print(f"\n管线 · {res['project']} · 场次 {res['scene']['id']}"
          f"（{res['scene'].get('name','')}）")
    print("─" * 78)
    for s in res["stages"]:
        n = s["report"]["errors"]
        w = s["report"]["warns"]
        tail = f"  ERROR {n} / WARN {w}"
        wait = ""
        if s.get("waiting_on") and s["status"] != "pass":
            wait = f"（轮不到：上面卡在 {s['waiting_on']}）"
        elif s.get("waiting_on"):
            wait = f"（要先过 {s['waiting_on']}）"
        tag = {"prog": "程序", "agent": "agent", "user": "用户"}[s["executor"]]
        lock = " 🔒" if s["seal_required"] else ""
        print(f"{icon[s['status']]} {s['id']:<4} {s['name']:<22} [{tag}]{lock}{tail} {wait}")
        for it in s["report"]["items"]:
            if it["level"] == "ERROR":
                print(f"      ❌ [{it['code']}] {it['msg']}")
            elif it["level"] == "WARN":
                print(f"      ⚠️  [{it['code']}] {it['msg']}")
    print("─" * 78)
    nxt = res.get("next_action")
    if nxt is None:
        print("🎬 全阶段通过")
    else:
        st = STAGE_BY_ID[nxt]
        who = {"prog": "程序自己跑", "agent": "交给 agent", "user": "等你拍板"}[st.executor]
        print(f"👉 当前卡在 {st.id} {st.name} —— {who}")
        if st.executor == "agent":
            print(f"   拿作业单：python tools/pipeline.py brief {res['project']} {st.id}")


def cmd_brief(proj: Path, stage_id: str, scene_id: str | None) -> int:
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)
    st = STAGE_BY_ID[stage_id]
    res = scan(proj, scene_id, only=stage_id)
    row = res["stages"][0]
    print(f"# 作业单 · {st.id} {st.name}\n")
    print(f"**项目**：{proj.name}　**场次**：{scene['id']} {scene.get('name','')}"
          f"　**执行者**：{st.executor}")
    print(f"\n**这一阶段为什么存在**：{st.why}\n")
    print("## 先读这些方法（**不要凭记忆写**）")
    for m in st.methods:
        p = proj / m if (proj / m).exists() else ROOT / m
        print(f"- `{p}`　{'（在）' if p.exists() else '⚠️ **不在，先确认路径**'}")
    if SKILL_MAP.get(st.id):
        print("\n## 外部方法（**判断依据，不是可以直接抄的规矩**）")
        for s in SKILL_MAP[st.id]:
            print(f"- **{s['src']}** —— {s['what']}")
    print("\n## 当前门禁（现场跑的）")
    if row["report"]:
        for it in row["report"]["items"]:
            mark = {"ERROR": "❌", "WARN": "⚠️ ", "INFO": "ℹ️ "}[it["level"]]
            print(f"- {mark} **[{it['code']}]** {it['msg']}")
            for k, v in it.items():
                if k not in ("level", "code", "msg"):
                    print(f"    - {k}: {v}")
    print("\n## 你要交的东西")
    for p in (st.produces or ["（见门禁里的 fix）"]):
        print(f"- `{p}`")
    print(f"\n## 交完怎么验（**由程序跑，不是由你说**）")
    print(f"```\npython tools/pipeline.py gate {proj.name} {st.id}"
          + (f" --scene {scene['id']}" if scene_id else "") + "\n```")
    if st.seal_required:
        print(f"\n⚠️ 这一阶段**必须留判定封条**：跑上面的 gate 拿审计包 → 出判定 JSON → "
              f"`pipeline.py seal`。没有封条，S8 不会放行到 GPU。")
    return 0


def cmd_seal(proj: Path, stage_id: str, verdict_file: str) -> int:
    """阶段级封条的落库。真正的哈希绑定交给 pipeline_audit 的封条机制。"""
    st = STAGE_BY_ID[stage_id]
    vf = Path(verdict_file)
    if not vf.is_absolute():
        vf = ROOT / vf
    if not vf.exists():
        raise SystemExit(f"❌ 判定文件不存在：{vf}")
    v = json.loads(read(vf))
    d = proj / "review" / "audits"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{stage_id}.verdict.json"
    out.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"🔒 已登记 {st.id} 判定 → {out.relative_to(proj)}")
    if st.seal_required:
        print("   这一阶段还要走 pipeline_audit 的封条（哈希绑定）：")
        print(f"   python tools/pipeline_audit.py seal {proj.name} <主题> <判定.json>")
    return 0 if v.get("verdict") != "fail" else 1


# ══════════════════════════════════════════════════════════════════════
#  MP4 容器解析（**本机没有 ffprobe，所以自己解**）
# ══════════════════════════════════════════════════════════════════════
def _boxes(buf: bytes, start: int, end: int):
    """按 ISO-BMFF 走一遍 box 链表，yield (type, payload_start, payload_end)。"""
    i = start
    while i + 8 <= end:
        size = int.from_bytes(buf[i:i + 4], "big")
        typ = buf[i + 4:i + 8].decode("latin-1")
        hdr = 8
        if size == 1:                       # 64 位 largesize
            if i + 16 > end:
                return
            size = int.from_bytes(buf[i + 8:i + 16], "big")
            hdr = 16
        elif size == 0:                     # 到文件尾
            size = end - i
        if size < hdr or i + size > end:
            return
        yield typ, i + hdr, i + size
        i += size


def _find(buf: bytes, start: int, end: int, path: list[str]):
    """按路径找 box，返回 (payload_start, payload_end)；找不到返回 None。"""
    if not path:
        return start, end
    for typ, s, e in _boxes(buf, start, end):
        if typ == path[0]:
            r = _find(buf, s, e, path[1:])
            if r:
                return r
    return None


def probe_mp4(path: Path) -> dict:
    """解出 时长／分辨率／帧率／帧数／有无音轨／音频采样率。

    **不猜**：任何一项解不出来就留 None，并记进 `unparsed`。
    用途见 `pipeline/docs/07_管线.md` §六 —— 机械能判的只有这些，
    画面内容（乱码文字／景别／服装）它一概不管。
    """
    buf = path.read_bytes()
    out: dict = {"file": path.name, "bytes": len(buf), "unparsed": []}
    moov = _find(buf, 0, len(buf), ["moov"])
    if not moov:
        out["unparsed"].append("没有 moov（不是 MP4？）")
        return out

    mv = _find(buf, moov[0], moov[1], ["mvhd"])
    ts = dur = None
    if mv:
        ver = buf[mv[0]]
        if ver == 0:
            ts = int.from_bytes(buf[mv[0] + 12:mv[0] + 16], "big")
            dur = int.from_bytes(buf[mv[0] + 16:mv[0] + 20], "big")
        else:
            ts = int.from_bytes(buf[mv[0] + 20:mv[0] + 24], "big")
            dur = int.from_bytes(buf[mv[0] + 24:mv[0] + 32], "big")
    if ts:
        out["timescale"] = ts
        out["duration_s"] = round(dur / ts, 3)
    else:
        out["unparsed"].append("mvhd 里读不到 timescale")

    tracks = []
    for typ, s, e in _boxes(buf, moov[0], moov[1]):
        if typ != "trak":
            continue
        h = _find(buf, s, e, ["mdia", "hdlr"])
        kind = buf[h[0] + 8:h[0] + 12].decode("latin-1") if h else "?"
        stsd = _find(buf, s, e, ["mdia", "minf", "stbl", "stsd"])
        stts = _find(buf, s, e, ["mdia", "minf", "stbl", "stts"])
        nframes = None
        if stts:
            n = int.from_bytes(buf[stts[0] + 4:stts[0] + 8], "big")
            tot = 0
            for k in range(n):
                o = stts[0] + 8 + k * 8
                tot += int.from_bytes(buf[o:o + 4], "big")
            nframes = tot
        ent = None
        if stsd:
            # stsd: ver+flags(4) entry_count(4) → 第一个 sample entry
            p = stsd[0] + 8
            if p + 8 <= stsd[1]:
                esz = int.from_bytes(buf[p:p + 4], "big")
                ent = (buf[p + 4:p + 8].decode("latin-1"), p, min(p + esz, stsd[1]))
        tr = {"kind": kind, "codec": ent[0] if ent else None, "frames": nframes}
        if ent and kind == "vide":
            tr["width"] = int.from_bytes(buf[ent[1] + 32:ent[1] + 34], "big")
            tr["height"] = int.from_bytes(buf[ent[1] + 34:ent[1] + 36], "big")
        if ent and kind == "soun":
            sr = int.from_bytes(buf[ent[1] + 32:ent[1] + 36], "big") >> 16
            tr["sample_rate"] = sr
            tr["channels"] = int.from_bytes(buf[ent[1] + 24:ent[1] + 26], "big")
        tracks.append(tr)
    out["tracks"] = tracks
    v = next((t for t in tracks if t["kind"] == "vide"), None)
    a = next((t for t in tracks if t["kind"] == "soun"), None)
    if v:
        out["width"], out["height"] = v.get("width"), v.get("height")
        out["video_codec"], out["frames"] = v.get("codec"), v.get("frames")
        if out.get("duration_s") and v.get("frames"):
            out["fps"] = round(v["frames"] / out["duration_s"], 3)
    else:
        out["unparsed"].append("没有视频轨")
    out["has_audio"] = a is not None
    if a:
        out["audio_codec"] = a.get("codec")
        out["audio_sample_rate"] = a.get("sample_rate")
        out["audio_channels"] = a.get("channels")
    else:
        out["unparsed"].append("**没有音轨**")
    return out


# ══════════════════════════════════════════════════════════════════════
#  S9 合规检查：**机械部分由程序填，语义部分留空等人**
# ══════════════════════════════════════════════════════════════════════
SEMANTIC_ITEMS = [
    ("画面可见文字", "有没有乱码字、招牌价签上的字对不对（买肉场那次横幅出的是乱码，"
                     "而我把它记成了「无乱码文字」）"),
    ("景别与机位", "实际框景与镜头表登记的 lens_mm／dist_m／visible_w_m 对不对"
                   "（S03 该是 85mm/1.4m 大特写，成片明显更宽）"),
    ("服装与造型", "围裙、胡子、签名标记（疤）在成片里对不对"),
    ("站位与轴线", "两人的画面左右有没有换位、有没有越轴"),
    ("音轨内容", "有没有人声、台词对不对、口型落在谁脸上 —— **这台机器没人听过**"),
]


def cmd_qc(proj: Path, scene_id: str | None, write: bool, as_json: bool) -> int:
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)
    want_canvas = rules.get("canvas") or [None, None]
    fps = scene["fps"]
    machine = []
    for s in (scene.get("t") or {}).get("shots") or []:
        sid = s.get("id")
        hits = sorted((proj / "outputs").glob(f"*{sid}*.mp4"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not hits:
            machine.append({"shot": sid, "item": "产物", "expect": "有 mp4",
                            "got": "没有", "result": "fail"})
            continue
        if len(hits) > 1:
            # 同镜多版**本身就是要人拍板的事** —— 程序不许替人选"哪一版是采用的"
            machine.append({
                "shot": sid, "item": "采用版本", "expect": "一镜一版",
                "got": "／".join(p.name for p in hits),
                "result": "fail",
                "detail": "同一镜有多个产物；下面核的是最新那个（按 mtime）。"
                          "**哪一版是采用的必须由人写下来**，程序不替人选"})
        info = probe_mp4(hits[0])
        def chk(item, exp, got):
            ok = (exp == got)
            machine.append({"shot": sid, "item": item, "expect": exp, "got": got,
                            "result": "pass" if ok else "fail",
                            "file": hits[0].name})
        chk("画布", f"{want_canvas[0]}×{want_canvas[1]}",
            f"{info.get('width')}×{info.get('height')}")
        chk("帧数", s.get("frames"), info.get("frames"))
        exp_dur = round((s.get("frames") or 0) / fps, 2)
        got_dur = info.get("duration_s")
        machine.append({"shot": sid, "item": "时长",
                        "expect": f"{exp_dur}s", "got": f"{got_dur}s",
                        "result": "pass" if got_dur and abs(got_dur - exp_dur) < 0.15
                                  else "fail", "file": hits[0].name})
        machine.append({"shot": sid, "item": "帧率", "expect": f"{fps}",
                        "got": f"{info.get('fps')}",
                        "result": "pass" if info.get("fps") and
                                  abs(info["fps"] - fps) < 0.5 else "fail",
                        "file": hits[0].name})
        machine.append({"shot": sid, "item": "音轨",
                        "expect": "有音轨（H3 原生 32kHz 立体声）",
                        "got": (f"{info.get('audio_codec')} "
                                f"{info.get('audio_sample_rate')}Hz "
                                f"{info.get('audio_channels')}ch"
                                if info.get("has_audio") else "**没有音轨**"),
                        "result": "pass" if info.get("has_audio") else "fail",
                        "file": hits[0].name})
        for u in info.get("unparsed", []):
            machine.append({"shot": sid, "item": "解析", "expect": "全部解出",
                            "got": u, "result": "fail", "file": hits[0].name})

    rec_path = proj / "review" / f"{scene['id']}_合规检查.json"
    old = {}
    if rec_path.exists():
        try:
            old = json.loads(read(rec_path))
        except ValueError:
            old = {}
    # **不覆盖人已经填过的语义结论** —— 程序只填机械部分
    old_sem = {x.get("item"): x for x in (old.get("checks") or [])
               if x.get("item") in [i[0] for i in SEMANTIC_ITEMS]}
    checks = list(machine)
    for item, why in SEMANTIC_ITEMS:
        prev = old_sem.get(item)
        checks.append(prev or {"item": item, "kind": "semantic", "why": why,
                               "result": "unchecked", "detail": ""})
    rec = {
        "_note": "S9 合规检查记录。**机械项由 `pipeline.py qc` 填；"
                 "语义项必须由 agent 或用户填，程序不猜。**"
                 "改动本文件后重新跑 `pipeline.py gate <项目> S9` 复核。",
        "scene": scene["id"],
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "canvas": want_canvas, "fps": fps,
        "checks": checks,
        "machine_summary": {
            "pass": sum(1 for c in machine if c["result"] == "pass"),
            "fail": sum(1 for c in machine if c["result"] == "fail"),
        },
        "semantic_summary": {
            "unchecked": sum(1 for c in checks
                             if c.get("kind") == "semantic"
                             and c.get("result") == "unchecked")},
        "verified_by_human": bool(old.get("verified_by_human", False)),
    }
    if as_json:
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    else:
        print(f"\nS9 合规检查 · {scene['id']} —— 机械项 "
              f"{rec['machine_summary']['pass']} 通过 / "
              f"{rec['machine_summary']['fail']} 不过")
        print("─" * 78)
        for c in machine:
            m = "✅" if c["result"] == "pass" else "❌"
            print(f"{m} {c['shot']}  {c['item']:<6} 期望 {c['expect']}　实测 {c['got']}")
        print("─" * 78)
        print(f"语义项 {len(SEMANTIC_ITEMS)} 条**未检查**（程序判不了，见文件里的 why）：")
        for item, _ in SEMANTIC_ITEMS:
            print(f"   ⬜ {item}")
    if write:
        rec_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n📝 已写入 {rec_path.relative_to(proj)}"
              f"（人填过的那几条保留不动）")
    else:
        print("\n（加 --write 落盘）")
    return 0 if rec["machine_summary"]["fail"] == 0 else 1


# ══════════════════════════════════════════════════════════════════════
#  S8 提交生成（**过了 S7 才允许**）
# ══════════════════════════════════════════════════════════════════════
def cmd_run(proj: Path, scene_id: str | None, only_shot: str | None,
            timeout: int, dry: bool) -> int:
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)

    # ① 先自己过一遍 S7 —— 不把"该不该跑"交给 run.py 单独判断
    s7 = gate_S7(proj, rules, scene, {})
    if not s7.ok():
        print("⛔ S7 审查提示词没过，不许提交：")
        for it in s7.errors:
            print(f"   ❌ [{it['code']}] {it['msg']}")
        print("\n先跑：python tools/pipeline.py brief "
              f"{proj.name} S7　→ 子 agent 出判定 → seal")
        return 1

    shots = [s for s in ((scene.get("t") or {}).get("shots") or [])
             if not only_shot or s.get("id") == only_shot]
    if not shots:
        print(f"❌ 没有匹配的镜头（{only_shot}）")
        return 1
    print(f"▶ 场次 {scene['id']}：{len(shots)} 镜，**按顺序**提交"
          f"（H3 一次只跑一个占显存的任务，规矩 §5.A.4）")
    for s in shots:
        wf = s.get("workflow")
        print(f"\n── {s['id']}  {wf}  {s.get('frames')} 帧 "
              f"{(s.get('frames') or 0)/scene['fps']:.2f}s")
        if dry:
            print("   （--dry 只列不跑）")
            continue
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "run.py"),
                            proj.name, wf, "--timeout", str(timeout)],
                           cwd=str(ROOT))
        if r.returncode != 0:
            print(f"   ⛔ {s['id']} 提交/运行失败，**停在这里不往下跑** ——"
                  f"云机一次只跑一个任务，继续跑会把队列搞乱")
            return r.returncode
    print("\n✅ 全部提交完成。回来跑："
          f"python tools/pipeline.py qc {proj.name} --scene {scene['id']} --write")
    return 0


# ══════════════════════════════════════════════════════════════════════
#  S4 脚手架：**机械可抽的先抽出来，抽不出的留空等人**
# ══════════════════════════════════════════════════════════════════════
def cmd_scaffold(proj: Path, scene_id: str | None, write: bool) -> int:
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)
    t = scene.get("t") or {}
    beats = {}
    rel = rules.get("script")
    if rel and (proj / rel).exists():
        beats = PA.parse_script(proj / rel)

    # 机械能抽的：镜头表里出现的角色称呼、场景 id、戏里提到的具名物件
    names: dict[str, set] = {}
    for s in t.get("shots") or []:
        for key in ("characters_on_screen", "props", "cast"):
            for x in (s.get(key) or []):
                names.setdefault(key, set()).add(x)
    blob = json.dumps(t, ensure_ascii=False) + "".join(
        " ".join(v["channels"]["画面"]) for v in beats.values())
    known = [c for c in (rules.get("characters") or {})
             if (rules["characters"][c].get("name") in blob)]
    manifest = {
        "_note": "**脚手架，不是成品。** 机械能抽的已经抽出来；"
                 "带 `TODO` 的地方必须由 agent 补全，补完跑 "
                 "`pipeline.py gate <项目> S5` 复核。",
        "scene": scene["id"],
        "characters": [
            {"id": cid, "name": (rules["characters"][cid].get("name")),
             "files": (rules["characters"][cid].get("files") or []),
             "signature": rules["characters"][cid].get("signature"),
             "used_in": [s.get("id") for s in (t.get("shots") or [])
                         if cid in json.dumps(s, ensure_ascii=False)],
             "TODO": "确认造型与本场服装；把本场独有的状态（围裙/湿手/伤口）写清楚"}
            for cid in known],
        "props": [{"id": "TODO", "name": "TODO", "files": [],
                   "TODO": "从戏的「画面」通道里挑出**必须跨镜一致**的物件"
                           "（手机、砍刀、挂肉、价签…）"}],
        "scenes": [{"id": scene["id"], "name": scene.get("name", ""),
                    "files": (rules.get("scenes", {}).get(scene["id"], {})
                              .get("files") or []),
                    "TODO": "确认 plan／cams／hero 三件都在，并登记 GEO 文件"}],
        "extracted_from": {"shot_table": scene["file"],
                           "beats_with_visual": [b for b, v in beats.items()
                                                 if v["channels"]["画面"]]},
    }
    if write:
        f = proj / "storyboard" / f"{scene['id']}_资产清单.json"
        if f.exists():
            print(f"⛔ 已存在，**不覆盖**：{f.relative_to(proj)}"
                  f"（要重做请自己先移走）")
            return 1
        f.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"📝 已写 {f.relative_to(proj)}")
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("\n（加 --write 落盘；已存在时不覆盖）")
    return 0


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="漫剧制作管线（阶段状态机 + 程序兜底）")
    ap.add_argument("cmd", choices=["stages", "scenes", "status", "gate", "verify",
                                    "brief", "seal", "ui", "json", "qc", "run",
                                    "scaffold", "probe"])
    ap.add_argument("project")
    ap.add_argument("target", nargs="?", help="阶段 id / 文件（gate/brief/seal/probe 用）")
    ap.add_argument("verdict", nargs="?", help="seal 用：判定 JSON")
    ap.add_argument("--scene", default=None)
    ap.add_argument("--shot", default=None, help="run 用：只跑某一镜")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--write", action="store_true", help="qc/scaffold 落盘")
    ap.add_argument("--dry", action="store_true", help="run 用：只列不跑")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()

    proj = project_dir(a.project)

    if a.cmd == "probe":
        if not a.target:
            ap.error("probe 需要一个 mp4 路径")
        p = Path(a.target)
        if not p.is_absolute():
            p = proj / a.target
        print(json.dumps(probe_mp4(p), ensure_ascii=False, indent=2))
        return 0

    if a.cmd == "qc":
        return cmd_qc(proj, a.scene, a.write, False)

    if a.cmd == "run":
        return cmd_run(proj, a.scene, a.shot, a.timeout, a.dry)

    if a.cmd == "scaffold":
        return cmd_scaffold(proj, a.scene, a.write)

    if a.cmd == "stages":
        print(f"{'阶段':<6}{'名称':<24}{'执行者':<8}封条  说明")
        for s in STAGES:
            print(f"{s.id:<6}{s.name:<24}"
                  f"{ {'prog':'程序','agent':'agent','user':'用户'}[s.executor] :<8}"
                  f"{'🔒' if s.seal_required else '  '}    {s.why}")
        return 0

    if a.cmd == "scenes":
        rules = PA.load_rules(proj)
        for s in find_scenes(proj, rules):
            print(f"- {s['id']:<10} {s.get('name',''):<20} {s['shots']} 镜 / "
                  f"{s['frames']} 帧 / {s['frames']/s['fps']:.2f}s　{s['file']}")
        return 0

    if a.cmd in ("status", "verify", "json"):
        res = scan(proj, a.scene)
        if a.cmd == "json":
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print_status(res)
        return 0 if all(s["status"] == "pass" for s in res["stages"]) else 1

    if a.cmd == "gate":
        if not a.target:
            ap.error("gate 需要阶段 id")
        res = scan(proj, a.scene, only=a.target)
        print_status(res)
        return 0 if res["stages"][0]["status"] == "pass" else 1

    if a.cmd == "brief":
        if not a.target:
            ap.error("brief 需要阶段 id")
        return cmd_brief(proj, a.target, a.scene)

    if a.cmd == "seal":
        if not a.target or not a.verdict:
            ap.error("seal 需要：<阶段 id> <判定.json>")
        return cmd_seal(proj, a.target, a.verdict)

    if a.cmd == "ui":
        import pipeline_ui
        return pipeline_ui.serve(proj, a.scene, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
