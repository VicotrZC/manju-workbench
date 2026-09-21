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
    """门禁结果。ERROR = 卡住，WARN = 提示，**PENDING = 产物还没产出，轮不到它**。

    PENDING 与 ERROR 分开的理由见 `pipeline_audit.Report` 的注释：
    「引用了一个还没产出的产物」和「引用了一个根本不存在的产物」是两件事。
    前者在 S2（首帧还没出）是正常的，后者在 S8（要推 GPU 了）才是致命的。
    """
    def __init__(self, stage: str):
        self.stage = stage
        self.items: list[dict] = []

    def e(self, code, msg, **kw):
        self.items.append({"level": "ERROR", "code": code, "msg": msg, **kw})

    def w(self, code, msg, **kw):
        self.items.append({"level": "WARN", "code": code, "msg": msg, **kw})

    def i(self, code, msg, **kw):
        self.items.append({"level": "INFO", "code": code, "msg": msg, **kw})

    def p(self, code, msg, **kw):
        self.items.append({"level": "PENDING", "code": code, "msg": msg, **kw})

    @property
    def errors(self):
        return [x for x in self.items if x["level"] == "ERROR"]

    @property
    def warns(self):
        return [x for x in self.items if x["level"] == "WARN"]

    @property
    def pendings(self):
        return [x for x in self.items if x["level"] == "PENDING"]

    def ok(self):
        return not self.errors

    def dump(self):
        return {"stage": self.stage, "ok": self.ok(),
                "errors": len(self.errors), "warns": len(self.warns),
                "pending": len(self.pendings), "items": self.items}


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
    """选场次。**多份候选时不许静默挑一个** —— 必须由 audit_rules 指明，否则报错。

    2026-09-21 实测踩到：文件名是 `SCN01_镜头表.json`，而文件里的 `scene` 字段是 `SCN-01`。
    `gen` 按字段名去写文件，于是多出一份 `SCN-01_镜头表.json`；
    `sorted()` 把 `-`(0x2D) 排在 `0`(0x30) 前面，**程序就静默读了坏的那一份**。
    用户要的「程序兜底」，第一条就是：**歧义必须报错，不许替人挑。**
    """
    scenes = find_scenes(proj, rules)
    if not scenes:
        raise SystemExit(f"❌ {proj.name} 下没有 storyboard/*_镜头表.json —— 一个场次都没有，"
                         f"先走 S1/S2")
    if scene_id:
        key = scene_id.replace("-", "").lower()
        for s in scenes:
            if s["id"] == scene_id or s["file"] == scene_id or \
               Path(s["file"]).stem.replace("-", "").lower().startswith(key):
                return s
        raise SystemExit(f"❌ 没有这个场次：{scene_id}\n现有：{[s['id'] for s in scenes]}")
    if len(scenes) == 1:
        return scenes[0]
    # 多个场次：按 audit_rules.json 的顺序取第一个**明确指明的**方式。
    # ⚠️ 仍然不许"随便挑一个" —— 只认下面两种显式声明，都没有就报错。
    declared = (rules.get("shot_table") or "").replace("\\", "/")
    for s in scenes:
        if s["file"].replace("\\", "/") == declared:
            return s
    default_id = str(rules.get("default_scene") or "").strip()
    if default_id:
        key = default_id.replace("-", "").lower()
        for s in scenes:
            if s["id"] == default_id or \
               Path(s["file"]).stem.replace("-", "").lower().startswith(key):
                return s
        raise SystemExit(
            f"❌ audit_rules.json 的 `default_scene` = {default_id!r} 对不上任何镜头表：\n"
            + "\n".join(f"   - {s['id']}（{s['file']}，{s['shots']} 镜）" for s in scenes))
    raise SystemExit(
        f"❌ 找到 {len(scenes)} 份镜头表，且 audit_rules.json 没指明用哪一份：\n"
        + "\n".join(f"   - {s['file']}（{s['shots']} 镜）" for s in scenes)
        + "\n→ 三种办法（**程序不替你挑** —— 挑错了整场都白做）："
          "\n  ① 用 `--scene <场次>` 指定；"
          "\n  ② 在 audit_rules.json 里把 `default_scene` 写成你要的那一场；"
          "\n  ③ 把 `shot_table` 指向它。")


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
    """分镜门禁 = **schema ＋ 逻辑**。

    ⚠️ 2026-09-21 修的判据错位：这一关原来直接跑 `check_chain` 的 file 存在性，
    于是它要求「首帧文件必须在盘上」—— 而首帧是**拿镜头表里登记的名字**去出的，
    出图又排在它后面的 S6。**先有鸡还是先有蛋 → S2 永远过不去。**
    实测后果：模型跑满 3 轮、白烧额度、最后记一份假失败。

    所以这里用 `materials="pending"`：**引用还没产出的产物不算错**（那是 S6/S8 的事），
    S2 只管「这张表自己合不合规矩」。真到了推 GPU 那一刻还不存在，S8 会拦死。
    """
    r = Rep("S2")
    t = scene.get("t") or {}
    shots = t.get("shots") or []
    if not shots:
        r.e("S2-01", "镜头表里没有镜头")
        return r

    for s in shots:
        sid = s.get("id", "?")
        for k in ("id", "beats", "shot_size", "lens_mm", "dist_m", "frames",
                  "first_frame", "first_frame_workflow", "workflow"):
            if not s.get(k):
                r.e("S2-02", f"镜头 {sid} 缺字段 `{k}`")
        # ── 帧数网格：不落在 17k+5 上，H3 直接跑不出来 ──
        try:
            n = int(s.get("frames"))
            if (n - 5) % 17 != 0:
                r.e("S2-03", f"镜头 {sid} 的 frames={n} 不在 **17k+5** 网格上"
                             f"（…158/175/192…）—— H3 会直接跑不出来")
        except (TypeError, ValueError):
            r.e("S2-04", f"镜头 {sid} 的 frames 不是整数：{s.get('frames')!r}")

    # ── 一镜一条工作流：**共用就是"改完再跑"，上一镜的提示词没留档就没了** ──
    # 本项目 S02 的提示词就是这么丢的（镜头表 known_gaps 第 2 条）。
    for key, code, what in (("workflow", "S2-05", "镜头工作流"),
                            ("first_frame_workflow", "S2-06", "首帧工作流")):
        owner: dict[str, list[str]] = {}
        for s in shots:
            if s.get(key):
                owner.setdefault(s[key], []).append(s.get("id"))
        for name, ids in owner.items():
            if len(ids) > 1:
                r.e(code, f"{what} `{name}` 被 {len(ids)} 个镜头共用：{'、'.join(ids)}",
                    fix="一镜一条。共用意味着改提示词再跑，上一镜的提示词"
                        "没留档就丢了 —— 那正是本项目 S02 丢提示词的原因")

    # ── 逻辑：节拍覆盖（交给审计层，只有一份判据）──
    sub, _chain = PA.check_chain(proj, rules, materials="pending",
                                 table_rel=scene.get("file"))
    for it in sub.items:
        if it["level"] == "INFO":
            continue
        (r.e if it["level"] == "ERROR" else
         r.w if it["level"] == "WARN" else r.p)(it["code"], it["msg"],
                                                **{k: v for k, v in it.items()
                                                   if k not in ("level", "code", "msg")})
    if r.ok():
        pend = len(r.pendings)
        r.i("S2-OK", f"{len(shots)} 镜登记齐"
                     + (f"；另有 {pend} 项产物**还没出**（轮到 S6/S8 再拦）" if pend else ""))
    return r


def gate_S3(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """验分镜 = 核「分镜这张表本身合不合规矩」。

    ⚠️ 2026-09-21 修的判据错位：原来固定用 `materials="error"` 调 `check_chain`，
    于是 S3 要求「首帧图 / 工作流文件必须在盘上」—— **而那三样全是 S6 才产出的**，
    S3 排在 S6 前面（S3 产出 prompts/*.md，S6 产出 workflows/*.json）。
    结果：S3 永远不过 → S4 依赖 S3 → **整条线在第一步死锁**。

    S3 的职责是**读镜头表，核站得住脚的东西**：节拍覆盖、字段齐、帧数网格、
    命名不串档。文件在不在，是 S6 写完、S8 推 GPU 之前才该拦的事。
    """
    rep, chain = PA.check_chain(proj, rules, materials="pending",
                                table_rel=scene.get("file"))
    r = Rep("S3")
    for it in rep.items:
        if it["level"] == "INFO":
            continue
        (r.e if it["level"] == "ERROR" else
         r.w if it["level"] == "WARN" else r.p)(it["code"], it["msg"],
                                                **{k: v for k, v in it.items()
                                                   if k not in ("level", "code", "msg")})
    if r.ok():
        pend = len(r.pendings)
        r.i("S3-OK", "节拍覆盖 / 镜头表 / 帧数网格 全部通过"
                     + (f"；另有 {pend} 项产物**还没出**（轮到 S6/S8 再拦）" if pend else ""))
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
    """验资产 = 核「这份清单对不对」，**不是核「图出了没有」**。

    ⚠️ 2026-09-21 修的判据错位（与 S2/S3 同一类病）：
    S4 的产出**就是**这份清单，而清单里登记的资产图要等**之后**去出。
    原来把"图不在盘上"报 ERROR，于是 S4 永远过不去 ——
    模型跑满 3 轮、把图片路径越改越离谱（实测第 3 轮它开始编 `PROP/PROP01_phone_alarm_00001.png`）。

    现在的分档：
    - **S5（这里）**：「清单自己合不合规矩」—— 每项有 id／有图登记／**真的被镜头表引用**。
    - **图在不在盘上**：PENDING。到**推 GPU 之前的 S8** 才提成 ERROR
      （`PA.check_chain` 那一侧同理；图是 `run.py` 出的，不是写清单时就在的）。
    """
    r = Rep("S5")
    f = proj / "storyboard" / f"{scene['id']}_资产清单.json"
    if not f.exists():
        r.e("S5-01", "资产清单不在（S4 没过）")
        return r
    m = json.loads(read(f))
    tbl = scene.get("t") or {}
    shots_txt = json.dumps(tbl, ensure_ascii=False)
    # 镜头表里这一场用了哪些资产图 —— 两种登记方式都认：
    #   ① 镜头对象的 `assets` 字段（规范 §P3 的 @锚点，结构化）
    #   ② 资产 id 直接出现在镜头表任何位置（老写法，兼容）
    per_shot: dict[str, list[str]] = {}
    for s in tbl.get("shots") or []:
        per_shot[s.get("id")] = list(s.get("assets") or [])
    for key in ("characters", "props", "scenes"):
        for a in (m.get(key) or []):
            aid = a.get("id", "?")
            files = a.get("files") or []
            if not files:
                r.e("S5-02", f"{aid} 没有登记任何资产图文件",
                    fix="01_资产规范 §〇：无图不进分镜。**先出图，再把路径登记进来**；"
                        "还没出的图不算错，但必须有一个明确的路径")
            for rel in files:
                if not (proj / "assets" / rel).exists() and \
                   not (proj / "outputs" / rel).exists():
                    # 图还没出 = 待产出，不是错
                    r.p("S5-03", f"{aid} 的图还没出：{rel}")
            # **资产必须真的被这一场的镜头用上** —— 买肉场就是资产做完了、一镜没用
            cited = [sid for sid, lst in per_shot.items() if aid in lst]
            if not cited and aid not in shots_txt:
                r.e("S5-04",
                    f"{aid} 在镜头表里**一次都没被引用** —— 做了资产却没用，"
                    f"成片和资产层脱钩",
                    fix="在镜头表的镜头对象里加 `assets` 字段挂上它；确实不用就删掉这一项")
    if r.ok():
        pend = len(r.pendings)
        r.i("S5-OK", "清单 schema / 被分镜引用 通过"
                     + (f"；另有 {pend} 张资产图**还没出**（轮到 S8 推 GPU 之前再拦）"
                        if pend else ""))
    return r


def gate_S6(proj: Path, rules: dict, scene: dict, state: dict) -> Rep:
    """写提示词：每镜跑全套 WF-* 不变量。

    **S6 的产出是「工作流文件」，不是「图」。** 所以：

    - `workflows/*.json` **必须真在** → 用 `materials="error"`
      （那是 S6 自己刚写的东西，S2/S3 那批 PENDING 在这里兑现）。
    - **首帧图不在不算错** → 那是「跑这条工作流」的结果，属于 S8。
      ⚠️ 2026-09-21 实测：这一关原来连首帧图一起要求，于是 **S6 永远过不去** ——
      因为首帧正是拿 S6 刚写的这条工作流去跑才有的。**又一处先有鸡还是先有蛋。**
      真正该拦的时点是 S8（要推 GPU 了）。S6 只判「提示词对不对」，
      因为那是**还没出图时唯一能判的东西**（画风句、GEO、身份锚、台词、禁字幕）。
    """
    r = Rep("S6")
    # 工作流文件必须都在；**首帧图允许还没出**（那是 S8 的事）
    _crep, chain = PA.check_chain(proj, rules, materials="pending",
                                  table_rel=scene.get("file"))
    for it in _crep.items:
        lv = it["level"]
        extra = {k: v for k, v in it.items() if k not in ("level", "code", "msg")}
        if lv == "ERROR":
            r.e(it["code"], it["msg"], **extra)
        elif lv == "PENDING":
            r.p(it["code"], it["msg"], **extra)
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
        pend = len(r.pendings)
        r.i("S6-OK", f"{done} 条工作流的提示词不变量全部通过"
                     + (f"；另有 {pend} 项产物待出（首帧图等，轮到 S8 拦）" if pend else ""))
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
    # ── 到这一刻，**首帧图必须真在盘上** ──
    # 首帧是"跑 S6 写的那条工作流"出来的。S6 放行它是因为当时还没跑；
    # 到了要推 GPU 这一刻还不在，就是真缺件 —— S2/S6 那批 PENDING 在这里兑现。
    _crep, _chain = PA.check_chain(proj, rules, materials="pending",
                                   table_rel=scene.get("file"))
    for it in _crep.items:
        if it["level"] == "PENDING":
            r.e(it["code"], f"要推 GPU 了，这项还不在：{it['msg']}",
                **{k: v for k, v in it.items() if k not in ("level", "code", "msg")})
    # ── 资产图也必须都在（S5 放行的 PENDING 在这里兑现）──
    am = proj / "storyboard" / f"{scene['id']}_资产清单.json"
    if am.exists():
        try:
            man = json.loads(read(am))
            for key in ("characters", "props", "scenes"):
                for a in (man.get(key) or []):
                    for rel in (a.get("files") or []):
                        if not (proj / "assets" / rel).exists() and \
                           not (proj / "outputs" / rel).exists():
                            r.e("S8-05",
                                f"要推 GPU 了，资产 {a.get('id')} 的图还不在盘上：{rel}",
                                fix="先出这张资产图并归档，再推 GPU —— "
                                    "01_资产规范 §〇：无图不进分镜")
        except ValueError:
            r.w("S8-06", f"资产清单不是合法 JSON：{am.name}")
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
            "only": only,
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
        p = s["report"].get("pending", 0)
        tail = f"  ERROR {n} / WARN {w}" + (f" / 待产出 {p}" if p else "")
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
        # PENDING 单列：**它不是错，但也不能藏起来** —— 到 S8 会被提成错
        pend = [it for it in s["report"]["items"] if it["level"] == "PENDING"]
        for it in pend[:3]:
            print(f"      ⏳ [{it['code']}] {it['msg']}")
        if len(pend) > 3:
            print(f"      ⏳ …另有 {len(pend) - 3} 项同类（step 没走到，不算错）")
    print("─" * 78)
    nxt = res.get("next_action")
    # ⚠️ `gate <项目> <阶段>` 只扫一个阶段，那时"没有 next_action"**不代表全线通过**。
    # 原来这里无条件打「🎬 全阶段通过」，单跑一个门禁也会显示全线绿 —— 假信号。
    partial = bool(res.get("only"))
    if nxt is None and partial:
        print(f"（只扫了 {res['only']} 一个阶段；这不是全线结论，"
              f"看全貌跑 `pipeline.py status {res['project']}`）")
    elif nxt is None:
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
#  S7 的批量动作：逐镜出审计包 / 逐镜封存
# ══════════════════════════════════════════════════════════════════════
def _scenes_for_batch(proj: Path, rules: dict, scene_id: str | None,
                      all_scenes: bool) -> list[dict]:
    """批量命令要跑哪几场。

    ⚠️ **多场次项目下，"只跑默认那一场"是最危险的失败方式** ——
    它不报错，只是悄悄漏掉另一个场次（`audit-all` 少出包、`seal-all` 少封条）。
    所以 `--all-scenes` 存在，而且给了 `--scene` 又说 all 会直接报错，不猜。
    """
    if all_scenes and scene_id:
        raise SystemExit("❌ `--scene` 与 `--all-scenes` 不能同时给 —— 要全跑就别指定场次")
    if all_scenes:
        out = find_scenes(proj, rules)
        bad = [s for s in out if s.get("bad")]
        if bad:
            raise SystemExit("❌ 有镜头表读不出来，先修：" +
                             "；".join(f"{b['id']}（{b['bad']}）" for b in bad))
        return out
    return [pick_scene(proj, rules, scene_id)]


def cmd_audit_all(proj: Path, scene_id: str | None, all_scenes: bool = False) -> int:
    """给每一镜出审计包（preflight）。**这只是备料，判定由模型写。**"""
    rules = PA.load_rules(proj)
    scenes = _scenes_for_batch(proj, rules, scene_id, all_scenes)
    n = 0
    for scene in scenes:
        print(f"\n══ 场次 {scene['id']} {scene.get('name','')}")
        for s in (scene.get("t") or {}).get("shots") or []:
            wf = s.get("workflow")
            if not wf or not (proj / "workflows" / f"{wf}.json").exists():
                print(f"⚠️  {s.get('id')} 跳过（工作流不存在：{wf}）")
                continue
            print(f"── {s['id']}  {wf}")
            PA.cmd_preflight(proj, wf, rules, as_json=False)
            n += 1
    print(f"\n📦 出了 {n} 份审计包（.work/audit/packets/，{len(scenes)} 场）")
    print("   下一步：模型读审计包写判定 → review/audits/<工作流>.verdict.json")
    return 0


def cmd_seal_all(proj: Path, scene_id: str | None, all_scenes: bool = False) -> int:
    """把 `review/audits/<工作流>.verdict.json` 逐个封存。缺判定的报出来。"""
    rules = PA.load_rules(proj)
    scenes = _scenes_for_batch(proj, rules, scene_id, all_scenes)
    ok = miss = 0
    for scene in scenes:
        print(f"\n══ 场次 {scene['id']} {scene.get('name','')}")
        for s in (scene.get("t") or {}).get("shots") or []:
            wf = s.get("workflow")
            if not wf:
                continue
            vf = proj / "review" / "audits" / f"{wf}.verdict.json"
            if not vf.exists():
                print(f"⚠️  {s['id']}  {wf} —— 没有判定文件 {vf.name}，跳过")
                miss += 1
                continue
            print(f"── {s['id']}  {wf}")
            try:
                if PA.cmd_seal(proj, wf, str(vf), rules) == 0:
                    ok += 1
            except SystemExit as exc:
                print(f"   ⛔ {exc}")
                miss += 1
    print(f"\n🔒 封存 {ok} 条，缺/失败 {miss} 条（{len(scenes)} 场）")
    return 0 if miss == 0 else 1


# ══════════════════════════════════════════════════════════════════════
#  自动生成循环：**组请求 → 调模型 → 落盘 → 跑门禁 → 不过就打回重做**
# ══════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """你是漫剧制作管线里的**生成模块**，不是聊天助手。

铁律：
1. **只输出 JSON**，不要解释、不要寒暄、不要 Markdown 代码块以外的文字。
2. **不许编造**。所有内容必须来自给你的上游文本；上游没写的，不要自己加。
3. 上游写了的东西**不许丢** —— 丢了会被程序的门禁抓出来打回，白跑一轮。
4. 严格按给的 schema 输出，字段名一个字母都不能改。
"""


def _read_if(proj: Path, rel: str | None) -> str:
    if not rel:
        return ""
    p = proj / rel
    return read(p) if p.exists() else ""


def _beats_digest(proj: Path, rules: dict, scene: dict | None = None) -> str:
    """从戏文件里**只抽节拍表**（节拍是分镜唯一的权威）。

    2026-09-21：原来把整份戏塞进作业单，连带 §三秒数核算／§四自检／§五待决问题
    一起喂进去。那些章节对分镜没用，纯烧额度 —— 实测模型思考到 48063 字符把
    max_tokens 吃光，JSON 断在半句。**给模型的上下文要只有它真正要用的那部分。**

    同日拆场次后：**按场次读它自己那份戏**（`beat_scope[场次].script`），
    读不到才回落到项目级 `script`。
    """
    rel = None
    if scene:
        rel = (PA.scene_plan(rules, scene.get("id") or "").get("script"))
    rel = rel or rules.get("script")
    txt = _read_if(proj, rel)
    if not txt:
        return ""
    lines = txt.splitlines()
    out, on = [], False
    for ln in lines:
        if ln.startswith("## 二、") and "拍表" in ln:      # 九拍表 / 节拍表
            on = True
            continue
        if on and ln.startswith("## 三、"):
            break
        if on:
            out.append(ln)
    body = "\n".join(out).strip()
    return body or txt


def _gen_spec(stage_id: str, proj: Path, rules: dict, scene: dict) -> dict:
    """每个可生成阶段的「要什么、写到哪、写完用什么门禁验」。"""
    sid = scene["id"]
    t = scene.get("t") or {}

    if stage_id == "S2":
        # ⚠️ 写出路径**必须用 audit_rules.json 登记的那一个**，不许按 scene['id'] 拼 ——
        # 文件名 `SCN01_…` 与字段 `scene:"SCN-01"` 不一致，拼出来的会是另一个文件，
        # 于是项目里多出一份镜头表，程序静默读了坏的那份（2026-09-21 实测）。
        #
        # 拆场次后（同日）：**多场次项目的 `shot_table` 单值不再是本场的答案**，
        # 本场的镜头表就是 `scene['file']`（pick_scene 已经选中的那一份）。
        multi = len(find_scenes(proj, rules)) > 1
        out = scene.get("file") if multi else (
            rules.get("shot_table") or f"storyboard/{sid}_镜头表.json")
        # 本场自己的戏与 GEO（拆场次后一场一份）
        plan = PA.scene_plan(rules, sid)
        my_script = plan.get("script") or rules.get("script")
        my_geo = scene.get("t", {}).get("geo") or rules.get("geo_file")
        return {
            "name": "分镜（机器可读镜头表）",
            "out": out,
            "gate": "S3",
            "ask": f"""把这一场的戏改成**机器可读镜头表**。

## 上游：戏的节拍表（节拍是唯一权威，分镜只能认领，不能新增）
{_beats_digest(proj, rules, scene)}

## 上游：GEO 空间地图（站位/机位/光源）
{_read_if(proj, my_geo)}

## 现有的镜头表（**在它基础上改，别推倒重来**）
{json.dumps(t, ensure_ascii=False, indent=2) if t else "（还没有）"}

## 输出 schema（严格照抄字段名）
{{
  "scene": "{sid}", "scene_name": "...", "episode": "...",
  "canvas": [1376, 768], "fps": 24,
  "script": "{my_script}", "geo": "{my_geo}",
  "shots": [
    {{"id": "S01", "beats": ["B1"],
      "shot_size": "中景", "framing_en": "A static medium shot, camera at eye level ...",
      "camera": "CAM1", "lens_mm": 35, "dist_m": 3.5, "visible_w_m": 3.6,
      "frames": 175, "duration_s": 7.29,
      "first_frame": "首帧文件名.png",
      "first_frame_workflow": "出首帧的工作流名",
      "workflow": "这一镜的 H3 工作流名（一镜一个，不许共用）",
      "assets": ["CHR-01", "SCN-02"],
      "content": "这一镜演什么"}}
  ]
}}

## 硬约束
- **戏里每一个节拍 B? 都必须被至少一个镜头认领**；漏一拍就整段消失。
- 镜头不许认领戏里没有的节拍。
- frames 必须落在 **17k+5** 网格（5/22/39/56/73/90/107/124/141/158/175/192/209/226…）。
- 一镜一条工作流，**不许两镜共用同一个 workflow 名**。
- 一镜一条首帧工作流，**`first_frame_workflow` 也不许两镜共用**。
- 每镜必须有独立的 first_frame。
- beats 里的编号必须真实存在于上面的戏里。
- **`assets` 必须写全这一镜真的用到的资产**（角色／道具／场景的 id）。
  这是 `01_资产规范` §P3 的 `@锚点` —— 没有它，"资产做完了却一镜没用"就无人发现。
  编号前缀照规范：角色 `CHR-<两位>`、场景 `SCN-<两位>`、道具 `PRP-<两位>`。
- **每条 `content` 一句话说完**（这是给人的摘要，不是剧本）；`framing_en` 一行。

## 命名规则（**必须照抄格式，编号随镜号变**）
把 `<ID>` 换成该镜的镜号（如 S00、S01）：
- `workflow`             = `EP02SC01_<ID>_h3`        → 写完是 `workflows/EP02SC01_<ID>_h3.json`
- `first_frame_workflow` = `FF_EP02SC01_<ID>`        → 写完是 `workflows/FF_EP02SC01_<ID>.json`
- `first_frame`          = `FF_EP02SC01_<ID>_00001_.png`　（落在 `outputs/`，由上面那条工作流出图；
  序号 `00001_` 是第一次跑，重跑会自增）

> 这三条**不是建议**：盘上真名就是这个规律（`outputs/FF_EP02SC01_S01_00002_.png` 等）。
> 不要自创 `mz_*.png` 这类名字 —— 出图程序不会产出它，那一镜就永远拿不到首帧。
> **首帧图此刻还不存在是正常的**（要等出图），但**文件名必须一次写对**。

## 输出纪律（**违反会被打回重做**）
- 顶层**只写 schema 里列出的字段**。不要 `_about`、不要 `known_gaps`、
  不要任何 `_` 开头的注释字段 —— 说明文字一律省略。
- 不要输出任何 schema 之外的键。
- **省掉说明性文字，把额度留给 shots 数组本身。**""",
        }

    if stage_id == "S4":
        old = _read_if(proj, f"storyboard/{sid}_资产清单.json")
        return {
            "name": "抽离角色／道具／场景",
            "out": f"storyboard/{sid}_资产清单.json",
            "gate": "S5",
            "ask": f"""从这一场的戏与镜头表里**抽出需要跨镜一致的角色／道具／场景**。

## 上游：戏
{_read_if(proj, rules.get('script'))}

## 上游：镜头表
{json.dumps(t, ensure_ascii=False, indent=2)}

## 上游：项目已登记的角色锁定件（**签名标记必须原样带过来**）
{json.dumps(rules.get('characters') or {}, ensure_ascii=False, indent=2)}

## 现有清单（如果有，在它基础上改）
{old or "（还没有）"}

## 输出 schema
{{
  "scene": "{sid}",
  "characters": [{{"id":"CHR-01","name":"...","files":["资产图相对路径"],
                   "signature":"签名标记原文","used_in":["S01","S02"],
                   "costume":"本场造型（围裙/湿手/伤口之类）"}}],
  "props":      [{{"id":"PROP-01","name":"...","files":[],"used_in":["S03"],
                   "why":"为什么它必须跨镜一致"}}],
  "scenes":     [{{"id":"{sid}","name":"...","files":[],"used_in":["S01"]}}]
}}

## 硬约束
- 三段（characters / props / scenes）**都必须有**，空的写 []。
- 每项必须有 id；characters 必须有 signature。
- **不许留 TODO**。
- 每一项的 id 必须能在镜头表里被引用到（`used_in` 里写清哪几镜用它）。""",
        }

    if stage_id == "S7":
        return {
            "name": "审查提示词（出判定）",
            "out": None,             # 每镜一个判定文件
            "gate": "S7",
            "ask": None,             # 每镜单独组
        }

    raise SystemExit(f"❌ {stage_id} 还没有生成规格（目前支持 S2 / S4 / S7）")


def _gen_once(proj: Path, stage_id: str, rules: dict, scene: dict,
              ask: str, out_rel: str, gate_id: str, prior_errors: list,
              attempt: int, total: int) -> tuple[bool, str]:
    """跑一轮：组消息 → 调模型 → 落盘 → 跑门禁。返回 (过没过, 说明)。"""
    import llm
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    body = ask
    if prior_errors:
        body += ("\n\n## ⚠️ 上一轮没过，门禁报出这些错 —— **逐条改掉，不要重蹈**\n"
                 + "\n".join(f"- [{e['code']}] {e['msg']}" for e in prior_errors))
    msgs.append({"role": "user", "content": body})

    print(f"\n── 第 {attempt}/{total} 轮：请求模型…")
    try:
        data = llm.chat_json(msgs)
    except Exception as exc:                       # noqa: BLE001
        msg = str(exc)
        # ── 截断/空正文/JSON 坏了 → **当成"这一轮没过"打回重做**，不当致命错误 ──
        # 2026-09-21 实测：模型思考 48063 字符吃光 max_tokens，JSON 断在半句。
        # 旧版在这里 return 失败 → **整轮生成直接退出，自动重做环白写了**。
        recoverable = any(k in msg for k in
                          ("JSON 解析失败", "找不到 JSON", "正文是空的", "Unterminated",
                           "Expecting", "截断"))
        hint = ("**上一轮你的输出被截断了，JSON 没写完。**"
                "\n→ 这一次把 `_about` / `known_gaps` 之类的说明字段**全部省掉**，"
                "\n  只写 schema 里的字段；每条 `content`/`framing_en` 压到一句话。"
                if recoverable else "")
        if recoverable and attempt < total:
            return False, [{"code": "GEN-01", "msg": f"模型调用失败：{msg[:600]}\n{hint}"}]
        return False, f"模型调用失败：{msg}"

    p = proj / out_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   落盘 {out_rel}（{p.stat().st_size} B）")

    rep = GATES[gate_id](proj, rules, pick_scene(proj, rules, scene["id"]), {})
    if rep.ok():
        print(f"   ✅ 门禁 {gate_id} 通过")
        return True, "ok"
    errs = rep.errors
    print(f"   ⛔ 门禁 {gate_id} 报 {len(errs)} 条，打回重做：")
    for e in errs[:8]:
        print(f"      ❌ [{e['code']}] {e['msg']}")
    return False, errs


# ══════════════════════════════════════════════════════════════════════
#  S6：写提示词与工作流 —— **模板法**
#
#  用户 2026-09-21 的架构要求：「模型负责生成和审查，执行面交给电脑」。
#  工作流是一张**几十个节点、二十几条连线**的图，让模型从零写必然出错
#  （节点 id 与 link id 对不上、连线指错端口 —— 而且这类错**在跑之前看不出来**）。
#
#  所以 S6 这样分工：
#
#  | 谁 | 干什么 |
#  |---|---|
#  | **程序** | 画节点图与连线（照已验证过的模板）／拼装全部锁定件 —— 画风句、GEO 英文块、 |
#  |          | 角色签名标记与正向否定锁、戏里的对白与 VO 原文、禁字幕句、帧数画布种子 |
#  | **模型** | 只写「镜次专属」的剧作文本：动作分段时间轴、音景、配乐、以及每个 Subject |
#  |          | 在拍内怎么演化 |
#
#  这样**锁定件不可能被模型改写或漏掉**（规矩 §5.C.12 的正解：
#  别指望模型记住，把它该记的东西从它手里拿走）。
# ══════════════════════════════════════════════════════════════════════

#: 首帧 t2i 的固定节点骨架（节点 id, 类型, 位置, widgets）。
#: 与实测生效的 `STYLE_I_H_mature.json` **同一套节点**（那是判过 pass 的画风标尺）。
T2I_GRAPH = [
    (1, "UNETLoader", [40, 40], ["qwen_image_2512_fp8_e4m3fn.safetensors", "default"]),
    (2, "CLIPLoader", [40, 170], ["qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image", "default"]),
    (3, "VAELoader", [40, 324], ["qwen_image_vae.safetensors"]),
    (4, "LoraLoaderModelOnly", [40, 430],
     ["Qwen-Image-2512-Lightning-8steps-V1.0-bf16.safetensors", 1.0]),
    (5, "CLIPTextEncode", [500, 40], None),          # ← 正向提示词（程序拼）
    (6, "CLIPTextEncode", [500, 370], [""]),         # ← 负向，CFG 1.0 下无效，保持空
    (7, "EmptySD3LatentImage", [500, 520], [1376, 768, 1]),
    (8, "KSampler", [1180, 40], None),               # ← 种子在这里，程序填
    (9, "VAEDecode", [1180, 340], []),
    (10, "SaveImage", [1180, 420], None),            # ← 前缀，程序填
]

#: H3 Ref2VA 的固定节点骨架。数值全部来自**已验证过的那条** S01 工作流
#: （`workflows/EP02SC01_S01_h3.json`，它真出过 175 帧的成片）。
H3_MODELS = {
    "unet": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae_video": "minimax_h3_video_vae_fp16.safetensors",
    "vae_audio": "minimax_h3_audio_vae_fp32.safetensors",
}


def build_t2i_workflow(prompt: str, prefix: str, seed: int, note: str = "",
                       canvas=(1376, 768), steps: int = 8) -> dict:
    """出首帧用的 t2i 工作流。**节点图由程序画，模型碰不到。**"""
    nodes, links = [], []
    by_id = {nid: (typ, pos, wv) for nid, typ, pos, wv in T2I_GRAPH}
    wv5 = [prompt]
    wv7 = [int(canvas[0]), int(canvas[1]), 1]
    wv8 = [seed, "fixed", steps, 1.0, "euler", "simple", 1.0]
    wv10 = [prefix]
    for nid, typ, pos, wv in T2I_GRAPH:
        wv = {5: wv5, 7: wv7, 8: wv8, 10: wv10}.get(nid, wv)
        nodes.append({
            "id": nid, "type": typ, "pos": pos,
            "size": {1: [420, 82], 2: [420, 106], 3: [420, 58], 4: [420, 82],
                     5: [640, 420], 6: [420, 120], 7: [420, 106], 8: [320, 262],
                     9: [220, 46], 10: [420, 300]}[nid],
            "flags": {}, "order": nid - 1, "mode": 0,
            "inputs": {4: [{"name": "model", "type": "MODEL", "link": 1}],
                       5: [{"name": "clip", "type": "CLIP", "link": 3}],
                       6: [{"name": "clip", "type": "CLIP", "link": 4}],
                       8: [{"name": "model", "type": "MODEL", "link": 2},
                           {"name": "positive", "type": "CONDITIONING", "link": 5},
                           {"name": "negative", "type": "CONDITIONING", "link": 6},
                           {"name": "latent_image", "type": "LATENT", "link": 7}],
                       9: [{"name": "samples", "type": "LATENT", "link": 8},
                           {"name": "vae", "type": "VAE", "link": 9}],
                       10: [{"name": "images", "type": "IMAGE", "link": 10}]}.get(nid, []),
            "outputs": {1: [{"name": "MODEL", "type": "MODEL", "links": [1], "slot_index": 0}],
                        2: [{"name": "CLIP", "type": "CLIP", "links": [3, 4], "slot_index": 0}],
                        3: [{"name": "VAE", "type": "VAE", "links": [9], "slot_index": 0}],
                        4: [{"name": "MODEL", "type": "MODEL", "links": [2], "slot_index": 0}],
                        5: [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [5], "slot_index": 0}],
                        6: [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [6], "slot_index": 0}],
                        7: [{"name": "LATENT", "type": "LATENT", "links": [7], "slot_index": 0}],
                        8: [{"name": "LATENT", "type": "LATENT", "links": [8], "slot_index": 0}],
                        9: [{"name": "IMAGE", "type": "IMAGE", "links": [10], "slot_index": 0}],
                        10: []}.get(nid, []),
            "widgets_values": wv,
            "properties": {"Node name for S&R": typ},
        })
        # 注意：**outputs[].links 与顶层 links 都要写**（规矩 §8 坑 1 说的是
        # 「判连通性必须用顶层 links」—— 不是说 outputs 可以空着）
    links = [[1, 1, 0, 4, 0, "MODEL"], [2, 4, 0, 8, 0, "MODEL"],
             [3, 2, 0, 5, 0, "CLIP"], [4, 2, 0, 6, 0, "CLIP"],
             [5, 5, 0, 8, 1, "CONDITIONING"], [6, 6, 0, 8, 2, "CONDITIONING"],
             [7, 7, 0, 8, 3, "LATENT"], [8, 8, 0, 9, 0, "LATENT"],
             [9, 3, 0, 9, 1, "VAE"], [10, 9, 0, 10, 0, "IMAGE"]]
    if note:
        nodes.append({
            "id": 11, "type": "MarkdownNote", "pos": [1660, 40], "size": [640, 620],
            "flags": {}, "order": 11, "mode": 0, "inputs": [], "outputs": [],
            "widgets_values": [note],
            "properties": {"Node name for S&R": "MarkdownNote"},
        })
    return {"last_node_id": nodes[-1]["id"], "last_link_id": 10, "nodes": nodes,
            "links": links, "groups": [], "config": {}, "extra": {}, "version": 0.4}


def build_h3_workflow(prompt: str, first_frame: str, prefix: str, seed: int,
                      frames: int, canvas=(1376, 768), note: str = "") -> dict:
    """H3 Ref2VA 视频工作流。**六段式提示词由程序拼，模型只供剧作文本。**"""
    C = int(canvas[0]); H = int(canvas[1])
    N = [
        (1, "UNETLoader", [40, 40], [H3_MODELS["unet"], "default"]),
        (2, "LoraLoaderModelOnly", [40, 170], [H3_MODELS["lora"], 1.0]),
        (3, "CLIPLoader", [40, 300], [H3_MODELS["clip"], "minimax", "default"]),
        (4, "VAELoader", [40, 450], [H3_MODELS["vae_video"]]),
        (5, "VAELoader", [40, 550], [H3_MODELS["vae_audio"]]),
        (6, "LoadImage", [40, 650], [first_frame, "image"]),
        # ⚠️ MiniMaxH3 节点的 widgets_values 布局：`[提示词, 宽, 高, 帧数]`。
        # 2026-09-21 实测：只给提示词的话 WF-11 说"布局与预期不同，帧数检查跳过" ——
        # **静默漏检**（画布与帧数两条最重要的机械不变量都没人查了）。
        (7, "MiniMaxH3ReferenceToVideo", [520, 40], [prompt, C, H, int(frames)]),
        (8, "RandomNoise", [1280, 40], [seed, "fixed"]),
        (9, "BasicGuider", [1280, 170], []),
        (10, "KSamplerSelect", [1280, 260], ["res_multistep"]),
        (11, "BasicScheduler", [1280, 360], ["simple", 4, 1.0]),
        (12, "SamplerCustomAdvanced", [1660, 40], []),
        (13, "VAEDecode", [1660, 220], []),
        (14, "VAEDecodeAudio", [1660, 300], []),
        (15, "CreateVideo", [1960, 40], [24.0]),
        (16, "SaveVideo", [1960, 200], [prefix, "auto", "auto"]),
    ]
    SIZE = {1: [420, 82], 2: [420, 82], 3: [420, 106], 4: [420, 58], 5: [420, 58],
            6: [320, 320], 7: [720, 560], 8: [320, 82], 9: [320, 46], 10: [320, 58],
            11: [320, 106], 12: [300, 130], 13: [220, 46], 14: [220, 46],
            15: [300, 106], 16: [420, 300]}
    IN = {
        2: [{"name": "model", "type": "MODEL", "link": 1}],
        6: [],
        7: [{"name": "clip", "type": "CLIP", "link": 2},
            {"name": "vae", "type": "VAE", "link": 3},
            {"name": "audio_vae", "type": "VAE", "link": 4},
            {"name": "ref_images.ref_image_0", "type": "IMAGE", "link": 5}],
        9: [{"name": "model", "type": "MODEL", "link": 9},
            {"name": "conditioning", "type": "CONDITIONING", "link": 10}],
        11: [{"name": "model", "type": "MODEL", "link": 11}],
        12: [{"name": "noise", "type": "NOISE", "link": 12},
             {"name": "guider", "type": "GUIDER", "link": 13},
             {"name": "sampler", "type": "SAMPLER", "link": 14},
             {"name": "sigmas", "type": "SIGMAS", "link": 15},
             {"name": "latent_image", "type": "LATENT", "link": 16}],
        13: [{"name": "samples", "type": "LATENT", "link": 17},
             {"name": "vae", "type": "VAE", "link": 18}],
        14: [{"name": "samples", "type": "LATENT", "link": 19},
             {"name": "vae", "type": "VAE", "link": 20}],
        15: [{"name": "images", "type": "IMAGE", "link": 21},
             {"name": "audio", "type": "AUDIO", "link": 22}],
        16: [{"name": "video", "type": "VIDEO", "link": 23}],
    }
    OUT = {
        1: [{"name": "MODEL", "type": "MODEL", "links": [1], "slot_index": 0}],
        2: [{"name": "MODEL", "type": "MODEL", "links": [9, 11], "slot_index": 0}],
        3: [{"name": "CLIP", "type": "CLIP", "links": [2], "slot_index": 0}],
        4: [{"name": "VAE", "type": "VAE", "links": [3, 18, 20], "slot_index": 0}],
        5: [{"name": "VAE", "type": "VAE", "links": [4, 19], "slot_index": 0}],
        6: [{"name": "IMAGE", "type": "IMAGE", "links": [5], "slot_index": 0},
            {"name": "MASK", "type": "MASK", "links": None, "slot_index": 1}],
        7: [{"name": "positive", "type": "CONDITIONING", "links": [10], "slot_index": 0},
            {"name": "LATENT", "type": "LATENT", "links": [16], "slot_index": 1}],
        8: [{"name": "NOISE", "type": "NOISE", "links": [12], "slot_index": 0}],
        9: [{"name": "GUIDER", "type": "GUIDER", "links": [13], "slot_index": 0}],
        10: [{"name": "SAMPLER", "type": "SAMPLER", "links": [14], "slot_index": 0}],
        11: [{"name": "SIGMAS", "type": "SIGMAS", "links": [15], "slot_index": 0}],
        12: [{"name": "LATENT", "type": "LATENT", "links": [17, 19], "slot_index": 0}],
        13: [{"name": "IMAGE", "type": "IMAGE", "links": [21], "slot_index": 0}],
        14: [{"name": "AUDIO", "type": "AUDIO", "links": [22], "slot_index": 0}],
        15: [{"name": "VIDEO", "type": "VIDEO", "links": [23], "slot_index": 0}],
        16: [],
    }
    nodes = [{"id": i, "type": t, "pos": p, "size": SIZE[i], "flags": {},
              "order": k, "mode": 0, "inputs": IN.get(i, []), "outputs": OUT.get(i, []),
              "widgets_values": wv, "properties": {"Node name for S&R": t}}
             for k, (i, t, p, wv) in enumerate(N)]
    if note:
        nodes.append({"id": 17, "type": "MarkdownNote", "pos": [2420, 40],
                      "size": [600, 720], "flags": {}, "order": len(N), "mode": 0,
                      "inputs": [], "outputs": [], "widgets_values": [note],
                      "properties": {"Node name for S&R": "MarkdownNote"}})
    links = [[1, 1, 0, 2, 0, "MODEL"], [2, 3, 0, 7, 0, "CLIP"],
             [3, 4, 0, 7, 1, "VAE"], [4, 5, 0, 7, 2, "VAE"],
             [5, 6, 0, 7, 3, "IMAGE"], [9, 2, 0, 9, 0, "MODEL"],
             [10, 7, 0, 9, 1, "CONDITIONING"], [11, 2, 0, 11, 0, "MODEL"],
             [12, 8, 0, 12, 0, "NOISE"], [13, 9, 0, 12, 1, "GUIDER"],
             [14, 10, 0, 12, 2, "SAMPLER"], [15, 11, 0, 12, 3, "SIGMAS"],
             [16, 7, 1, 12, 4, "LATENT"], [17, 12, 0, 13, 0, "LATENT"],
             [18, 4, 0, 13, 1, "VAE"], [19, 12, 0, 14, 0, "LATENT"],
             [20, 5, 0, 14, 1, "VAE"], [21, 13, 0, 15, 0, "IMAGE"],
             [22, 14, 0, 15, 1, "AUDIO"], [23, 15, 0, 16, 0, "VIDEO"]]
    _ = (C, frames)          # 画布与帧数由 H3 节点从首帧推出；这里只留接口
    return {"last_node_id": nodes[-1]["id"], "last_link_id": 23, "nodes": nodes,
            "links": links, "groups": [], "config": {}, "extra": {}, "version": 0.4}


# ── 拼装锁定件（**这些字一个都不许模型改**）────────────────────────────
def style_lock_text(rules: dict) -> str:
    """画风锁定句的原文（项目卡里逐字确认过的那一条）。"""
    locks = rules.get("style_locks") or {}
    for _nm, txt in locks.items():
        if txt:
            return txt
    return ""


def geo_block_text(proj: Path, rules: dict, scene: dict) -> str:
    """本场 GEO 空间地图的英文块（§2.3 要求逐字进 H3 提示词）。"""
    rel = (scene.get("t") or {}).get("geo") or rules.get("geo_file")
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


def shot_for_ff_workflow(scene: dict, wf_name: str) -> dict:
    """某条首帧工作流属于这一场次的哪个镜头。找不到返回 {}。"""
    for s in (scene.get("t") or {}).get("shots") or []:
        if s.get("first_frame_workflow") == wf_name:
            return s
    return {}


def p1_assets(proj: Path, rules: dict, scene: dict, shot: dict) -> dict:
    """这一镜用到的资产明细（从资产清单里按 `assets` 字段取）。"""
    am = proj / "storyboard" / f"{scene['id']}_资产清单.json"
    out = {"characters": [], "props": [], "scenes": []}
    if not am.exists():
        return out
    try:
        man = json.loads(read(am))
    except ValueError:
        return out
    want = set(shot.get("assets") or [])
    for key in ("characters", "props", "scenes"):
        for a in (man.get(key) or []):
            if a.get("id") in want:
                out[key].append(a)
    return out


def _beats_of(proj: Path, rules: dict, scene: dict) -> dict:
    plan = PA.scene_plan(rules, scene["id"])
    rel = plan.get("script") or rules.get("script")
    f = proj / rel if rel else None
    return PA.parse_script(f) if f and f.exists() else {}


def _lines_of(beats: dict, shot: dict) -> tuple[list[str], list[str]]:
    """这一镜认领的节拍里的（对白, VO）原文 —— **逐字，来自戏**。"""
    dlg, vo = [], []
    for b in shot.get("beats") or []:
        if b in beats:
            dlg += beats[b]["channels"]["对白"]
            vo += beats[b]["channels"]["VO"]
    return dlg, vo


def geo_cn_block(proj: Path, rel: str | None) -> str:
    """GEO 文件的中文版块（``` 内的那段）。"""
    if not rel or not (proj / rel).exists():
        return ""
    lines = read(proj / rel).splitlines()
    on, body, fence = False, [], False
    for ln in lines:
        if ln.startswith("## 一、"):
            on = True
            continue
        if on and ln.startswith("## 二、"):
            break
        if on and ln.strip().startswith("```"):
            if fence:
                break
            fence = True
            continue
        if on and fence:
            body.append(ln)
    return "\n".join(body).strip()


def build_t2i_prompt(proj: Path, rules: dict, scene: dict, shot: dict,
                     style: str, keep: str = "") -> str:
    """首帧 t2i 提示词。

    实测标定（`audit_rules.json` 的 `_style_ratio_about`）：
    **画风句必须在最前面**（WF-03：位置 > 20 字就报），而且**占比 ≥ 20%**（WF-04，t2i 下限）。
    画风句是固定 100 字，所以**描述段有硬预算**（约 400 字）—— 这是硬约束，不是风格偏好。

    语言（项目卡拍板记录第 2b 条）：**只有画风锁那一句用中文，其余保持英文。**

    ## 分级预算（2026-09-21 实测教训）

    第一版是"超预算就 break" —— 结果一条超长的场景句把后面**全丢了**，
    包括 `WF-07` 要核的身份锚英文原文。而且"丢掉"这件事本身**没有任何补偿动作**。
    现在按优先级分三档：**必需**（画风句／取景／身份锚／无文字）永远留；
    **重要**（人物装扮、道具）在预算内尽量留；**可压**（场景）最后留 —— 超了从它开始砍。
    """
    assets = p1_assets(proj, rules, scene, shot)
    rel = (scene.get("t") or {}).get("geo") or rules.get("geo_file")
    geo_cn = geo_cn_block(proj, rel)

    # ── ① 必需：画风句（第 0 字）+ 取景句 ──
    # ⚠️ 取景句用**完整原文**，不做精简。2026-09-21 模型审出来的：
    # 我原来用 `framing_en_compact` 只留前半句，结果「手机亮屏在暗处前景／环卫工在远处
    # 路尽头／闫清骑出画面朝菜市场」这些**构图信息全丢了** ——
    # 而首帧恰恰就是构图。省字数要从场景段省，不能从取景句省。
    must = [style]
    if shot.get("framing_en"):
        must.append(str(shot["framing_en"]).strip())
    # ── ② 必需：身份锚（WF-07 逐字核这句英文）+ 正向否定锁（WF-08）──
    who = []
    for c in assets["characters"]:
        bits = []
        if c.get("name"):
            bits.append(str(c["name"]))
        if c.get("costume"):
            bits.append(str(c["costume"]))
        if c.get("signature"):
            bits.append(str(c["signature"]))          # **英文原文，逐字**
        for lock in (c.get("positive_locks") or []):
            bits.append(str(lock))
        if bits:
            who.append("，".join(bits))
    # ── ③ 重要：道具 ──
    props = [f"道具：{pr.get('name','')}" for pr in assets["props"] if pr.get("name")]
    # ── ④ 可压：场景（只取中文 GEO 的头两条：场地与坐标系）──
    sc_bits = []
    if geo_cn:
        head = [ln.strip("— ").strip() for ln in geo_cn.splitlines()
                if ln.strip().startswith("—")]
        sc_bits = head[:2]
    scene_line = ("场景：" + "；".join(sc_bits) + "。") if sc_bits else ""
    if keep:
        must.append(keep)          # 取景复述：也是构图依据，算必需
    tail = "画面里是干净的无字画面。"

    floor = (rules.get("style_ratio_min") or {}).get("t2i", 0.2)
    style_n = len(PA.norm_ws(style))

    def nchars(x: str) -> int:
        return PA.noscript_chars(x)

    def assemble(parts: list[str]) -> str:
        seen, out = set(), []
        for p in parts:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return "\n".join(out)

    full = assemble(must + who + props + [scene_line, tail])
    if style_n / max(1, nchars(full)) >= floor:
        return full

    # 需要截短：**先砍场景，再砍道具**，必需项一个都不动
    print(f"   ⚠️ t2i 描述段 {nchars(full)} 字，画风句占比 {style_n / nchars(full):.1%}"
          f" 低于下限 {floor:.0%} —— 按优先级截短（先砍场景、再砍道具）")
    for drop in ([scene_line], [scene_line] + props[-1:], [scene_line] + props):
        cand = assemble(must + who + [p for p in props if p not in drop]
                        + ([scene_line] if scene_line not in drop else []) + [tail])
        if style_n / max(1, nchars(cand)) >= floor:
            return cand
    # 砍到只剩必需项还是不够 → 这是**内容问题**，报出来别自己硬改
    out = assemble(must + who + [tail])
    ratio = style_n / max(1, nchars(out))
    if ratio < floor:
        print(f"   ⛔ 砍到只剩必需项仍只有 {ratio:.1%}（画风句 {style_n} 字 / "
              f"上限 {int(style_n / floor)} 字）—— 取景句太长或身份锚太长，"
              f"要么精简它们，要么下调 style_ratio_min（**那是内容决定，交用户**）")
    return out


def framing_en_compact(shot: dict) -> str:
    """取景句的精简版（**已弃用，保留作对照**）。

    2026-09-21：我原来用它给 t2i 省字数，只留"机位与景别"那半句。
    模型审出来——**丢掉的正是构图信息**（手机屏在暗处前景、环卫工在远处路尽头、
    闫清骑出画面朝菜市场）。而首帧的唯一职责就是构图。
    → 现在 t2i 直接用 `framing_en` 完整原文，字数从场景段省。
    """
    f = (shot.get("framing_en") or "").strip()
    if not f:
        return ""
    head = f.split(",")[0].strip()
    return head + "." if head else f


def build_h3_prompt(proj: Path, rules: dict, scene: dict, shot: dict,
                    texts: dict, style: str, geo: str) -> str:
    """H3 六段式。**段序固定**（WF-01），且画风句与 GEO 块逐字在内。

    | 段 | 谁供 |
    |---|---|
    | `subject_definitions` | 程序：资产清单的人物＋签名标记＋`<Picture 1>`；模型补每人在拍内怎么演化 |
    | `summary`             | 模型（一句话说清这一镜是什么） |
    | `retention_analysis`  | 模型（逐 Subject 写保留策略，格式由程序保证） |
    | `detailed_description`| **程序**：画风句 → 取景 → GEO 块 → 动作时间轴（模型供）→ 台词（戏供）→ 禁字幕句 |
    | `overall_soundscape`  | 模型 |
    | `non_diegetic_music`  | 模型 |
    """
    assets = p1_assets(proj, rules, scene, shot)
    beats = _beats_of(proj, rules, scene)
    dlg, vo = _lines_of(beats, shot)
    sid = shot.get("id", "S??")

    # ── subject_definitions ──
    subjects = []
    for i, c in enumerate(assets["characters"], start=1):
        line = f"<Subject {i}> is {c.get('name','')}"
        if c.get("costume"):
            line += f", wearing {c['costume']}"
        if c.get("signature"):
            line += f". Identity anchor that must be visible: {c['signature']}"
        for lock in (c.get("positive_locks") or []):
            line += f". He is {lock}"
        ev = (texts.get("subject_evolution") or {}).get(c.get("id"))
        if ev:
            line += f". In [Shot 1] {ev}"
        subjects.append(line + ".")
    for j, pr in enumerate(assets["props"], start=len(subjects) + 1):
        ev = (texts.get("subject_evolution") or {}).get(pr.get("id"))
        subjects.append(f"<Subject {j}> is {pr.get('name','')}"
                        + (f". In [Shot 1] {ev}" if ev else "") + ".")
    for sc in assets["scenes"]:
        ev = (texts.get("subject_evolution") or {}).get(sc.get("id"))
        if ev:
            subjects.append(f"<Subject {len(subjects)+1}> is the location "
                            f"{sc.get('name','')}. In [Shot 1] {ev}.")
    subjects.append(
        f"<Picture 1> is the first frame of [Shot 1] and fixes the framing, "
        f"the camera position and the lighting. The shot scale is already final "
        f"in <Picture 1> and must not change.")

    # ── detailed_description ──
    dd = [style, ""]                                  # ① 画风句第 0 字（WF-03）
    dd.append(f"[Shot 1] {shot.get('framing_en','')}")
    dd.append("")
    dd.append(geo)                                    # ② GEO 逐字（WF-05）
    dd.append("")
    if texts.get("action_timeline"):
        dd.append(texts["action_timeline"])
        dd.append("")
    # ③ 台词：**逐字来自戏**（WF-09b 会逐句核对）
    spoke = []
    for k, ln in enumerate(dlg):
        who = texts.get("dialogue_speaker") or {}
        idx = who.get(str(k), who.get(k, 2))
        spoke.append(f"<Subject {idx}> (S{k+1}) says, <d>[Chinese] {ln}</d>")
    for k, ln in enumerate(vo):
        spoke.append(f"Off-screen voice-over (S{len(dlg)+k+1}), "
                     f"<d>[Chinese] {ln}</d>")
    if spoke:
        dd.append(" ".join(spoke))
    else:
        # ⚠️ 措辞必须命中 `pipeline_audit.NO_SPEECH_RE`（判据认的是
        # `no dialogue|nobody speaks|nobody's lips move|no one speaks|no voices|is silent`）。
        # **VO 是画外音**：现场没人张嘴，所以是"无人说话"，不是"没有声音"。
        dd.append("Neither man speaks in this shot and nobody's lips move; "
                  "the only voice is an off-screen voice-over.")
    dd.append("")
    dd.append("No subtitles, captions or on-screen text appear at any point.")
    fields = {
        "subject_definitions": "\n".join(subjects),
        "summary": texts.get("summary") or "",
        "retention_analysis": texts.get("retention_analysis") or "",
        "detailed_description": "\n".join(dd),
        "overall_soundscape": texts.get("overall_soundscape") or "",
        "non_diegetic_music": texts.get("non_diegetic_music") or "",
    }
    return "\n\n".join(f"{k}:\n{fields[k]}" for k in PA.H3_FIELDS)


def _s6_ask(proj: Path, rules: dict, scene: dict, shot: dict) -> str:
    """S6 的作业单：**只要剧作文本** —— 工作流图与全部锁定件由程序拼。"""
    beats = _beats_of(proj, rules, scene)
    dlg, vo = _lines_of(beats, shot)
    assets = p1_assets(proj, rules, scene, shot)
    geo = geo_block_text(proj, rules, scene)
    style = style_lock_text(rules)
    sid = shot["id"]
    names = [c.get("id") for c in assets["characters"]] + \
            [p.get("id") for p in assets["props"]] + \
            [s.get("id") for s in assets["scenes"]]
    return f"""给**一个镜头**写 H3 视频提示词里「属于创作」的那几段。

## 这一镜
镜号 {sid}｜{shot.get('shot_size','')}｜{shot.get('lens_mm')}mm｜{shot.get('dist_m')}m｜
{shot.get('frames')} 帧 ＝ {shot.get('duration_s')}s｜认领节拍 {'、'.join(shot.get('beats') or [])}

**取景（原样，别改写，程序会自己写进去）**：{shot.get('framing_en','')}
**这一镜演什么**：{shot.get('content','')}

## 戏里这一拍写了什么（**唯一权威，不许新增剧情**）
{chr(10).join(f'- {b}「{beats[b]["header"]}」' for b in (shot.get('beats') or []) if b in beats)}

**这一镜有对白 {len(dlg)} 句、VO {len(vo)} 句。**
对白原文（**程序会逐字写进 <d>，你只负责指定说话人**）：
{chr(10).join(f'  [{k}] {x}' for k, x in enumerate(dlg)) or '  （无）'}
VO 原文（同样由程序写）：
{chr(10).join(f'  [{k}] {x}' for k, x in enumerate(vo)) or '  （无）'}

## 这一镜用到的资产（id 与 name 都给你，**signature 由程序写**）
{json.dumps({k: [{'id': a.get('id'), 'name': a.get('name')} for a in v]
             for k, v in assets.items()}, ensure_ascii=False, indent=2)}

## 程序会把这些**一字不改**写进去，你**不要**重复它们
- 画风锁定句（{len(style)} 字，放 detailed_description 最前面）
- GEO 空间地图英文块（{len(geo)} 字，逐字，在取景句之后）
- 每个角色的签名标记与正向否定锁
- 戏里的每一句对白／VO 原文（包在 `<d>[Chinese] …</d>` 里）
- 禁字幕句 `No subtitles, captions or on-screen text appear at any point.`
- 取景句（`{shot.get('framing_en','')[:40]}…`）

## 输出 JSON（严格照抄字段名，不要多写一个字）
{{
  "action_timeline": "**英文**。这一镜的动作按秒分段的连续散文，格式：`0.0-1.5s … 1.5-3.5s …`，覆盖整个 {shot.get('duration_s')} 秒，最后一段必须落到「保持不动」之类不会让画面在结尾还在动的描述。只写看得见的动作，不许写台词。",
  "dialogue_speaker": {{"0": 说话人的 Subject 序号}},
  "subject_evolution": {{"CHR-01": "**英文**。这个人在这一镜里怎么动", "SCN-02": "…"}},
  "summary": "**英文**。两三句说清这一镜是什么、谁在做什么。若有 VO，写成画外音转述，不许写成人物的现场台词。",
  "retention_analysis": "**英文**。逐 Subject 一段：`<Subject N> (appears in [Shot 1]): fully_preserved — …`。",
  "overall_soundscape": "**英文**。这一镜的环境音。**不要**写人的说话声（除非戏里有对白）；有 VO 时环境音要给它留位置。",
  "non_diegetic_music": "**英文**。配乐。戏里说了不许变调／不许加悲鸣的地方要照办；没有配乐就写 `none`。"
}}

## 硬约束
- `action_timeline` **必须覆盖整段时长并且结尾收住**（旧线就因为没给时间预算，7.29 秒全花在开头动作上、结尾还在动）。
- `dialogue_speaker` 的序号要对应上面 assets 里 characters 的顺序（第 1 个 = 1）。
  **VO 是画外音，不要在 dialogue_speaker 里给它编号** —— 程序会自己写。
- 戏里没写的东西**一个字都不许加**。特别是：不许给猪加悲鸣、不许配乐变调、不许加旁白。
- 全部英文。**不要**在英文里夹中文。"""


def _gen_s6(proj: Path, rules: dict, scene: dict, rounds: int) -> int:
    """S6：逐镜问模型要剧作文本 → **程序拼工作流** → 落盘 → 跑 S6 门禁 → 不过打回。

    ⚠️ 与 S2/S4 的 `_gen_once` 不同：这里**模型不产出文件**，它只供文本，
    文件由 `build_*_workflow` 生成。所以不能复用 `_gen_once`（那是"模型直接吐 JSON 落盘"）。
    """
    import llm
    shots = (scene.get("t") or {}).get("shots") or []
    if not shots:
        print("❌ 这一场没有镜头，先跑 S2")
        return 1
    seat = int(json.loads(read(proj / "audit_rules.json")).get("seed_base") or 20260921)
    errs: list = []
    for i in range(1, rounds + 1):
        texts_by_shot: dict[str, dict] = {}
        print(f"\n── 第 {i}/{rounds} 轮：逐镜问模型要剧作文本…")
        for s in shots:
            ask = _s6_ask(proj, rules, scene, s)
            if errs:
                ask += ("\n\n## ⚠️ 上一轮没过，门禁报出这些错 —— **逐条改掉**\n"
                        + "\n".join(f"- [{e['code']}] {e['msg'][:300]}" for e in errs[:10]))
            try:
                data = llm.chat_json([{"role": "system", "content": SYSTEM_PROMPT},
                                      {"role": "user", "content": ask}])
            except Exception as exc:                       # noqa: BLE001
                msg = str(exc)
                print(f"   ⛔ {s['id']} 模型调用失败：{msg[:200]}")
                if any(k in msg for k in ("被截断", "正文是空的", "JSON")) and i < rounds:
                    errs = [{"code": "GEN-01",
                             "msg": f"{s['id']} 输出被截断/不是合法 JSON：{msg[:400]}"}]
                    texts_by_shot = {}
                    break
                return 1
            texts_by_shot[s["id"]] = data
            print(f"   ✓ {s['id']} 拿到剧作文本")
        if not texts_by_shot:
            continue

        # ── 程序拼工作流并落盘 ──
        style = style_lock_text(rules)
        geo = geo_block_text(proj, rules, scene)
        if not style:
            print("❌ audit_rules.json 没登记画风锁定句 —— 拼不出提示词")
            return 1
        canvas = (scene.get("t") or {}).get("canvas") or rules.get("canvas") or [1376, 768]
        for k, s in enumerate(shots):
            sid = s["id"]
            ffw = s.get("first_frame_workflow")
            wf = s.get("workflow")
            if not ffw or not wf:
                print(f"❌ {sid} 没登记 first_frame_workflow / workflow —— 先跑 S2")
                return 1
            texts = texts_by_shot.get(sid) or {}
            keep = ("**本镜取景必须在首帧里就做出来**："
                    f"{s.get('shot_size','')}，{s.get('lens_mm')}mm，距 {s.get('dist_m')}m。")
            t2i = build_t2i_prompt(proj, rules, scene, s, style, keep)
            (proj / "workflows" / f"{ffw}.json").write_text(
                json.dumps(build_t2i_workflow(
                    t2i, f"{rules.get('slug','proj')}/{ffw}",
                    seat + k, note=_t2i_note(scene, s, ffw),
                    canvas=canvas),
                    ensure_ascii=False, indent=2), encoding="utf-8")
            h3p = build_h3_prompt(proj, rules, scene, s, texts, style, geo)
            (proj / "workflows" / f"{wf}.json").write_text(
                json.dumps(build_h3_workflow(
                    # ⚠️ LoadImage 用**镜头表登记的那个文件名**（不带 `meishi/` 子目录）——
                    # 那是 `run.py` 落盘后的名字，也是审计比对的那个。
                    h3p, s.get("first_frame"),
                    f"{rules.get('slug','proj')}/{wf}", seat + 100 + k,
                    int(s.get("frames") or 175), canvas=canvas,
                    note=_h3_note(scene, s, wf)),
                    ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"   ✍️  写了 workflows/{ffw}.json 与 workflows/{wf}.json")
        _resync_prompts(proj)

        rep = GATES["S6"](proj, rules, pick_scene(proj, rules, scene["id"]), {})
        if rep.ok():
            print(f"\n🎬 S6 过了（第 {i} 轮）")
            return 0
        errs = rep.errors
        print(f"   ⛔ 门禁 S6 报 {len(errs)} 条，打回重做：")
        for e in errs[:8]:
            print(f"      ❌ [{e['code']}] {e['msg'][:160]}")
    fail_file = proj / "review" / "S6_生成失败.json"
    fail_file.parent.mkdir(parents=True, exist_ok=True)
    fail_file.write_text(json.dumps({
        "stage": "S6", "scene": scene["id"], "rounds": rounds, "last_errors": errs,
        "_note": "跑满轮数仍未过门禁。**别当它成功**；看 last_errors。"},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n⛔ S6 跑满 {rounds} 轮仍未过门禁，已记 {fail_file.name}")
    return 1


def _resync_prompts(proj: Path) -> None:
    """把刚写好的工作流里的正向提示词抽到 `prompts/<镜号>.prompt.md`。

    `prompts/` 是规矩 §1 的一层，也是**提示词能被 diff 的地方**。
    失败了不影响生成，只提醒。
    """
    try:
        PA.cmd_sync_prompts(proj, PA.load_rules(proj))
    except Exception as exc:                            # noqa: BLE001
        print(f"   ⚠️ 同步 prompts/ 失败（不影响工作流）：{exc}")


def _t2i_note(scene: dict, shot: dict, ffw: str) -> str:
    return (f"# {scene['id']} {shot['id']} · 首帧（t2i）\n\n"
            f"**本文件由 `pipeline.py gen S6` 用模板生成，不是手写的。**\n\n"
            f"| 项 | 值 |\n|---|---|\n"
            f"| 画布 | 1376×768 |\n| 步骤 | 8 步 / CFG 1.0 |\n"
            f"| 景别 | {shot.get('shot_size','')} |\n| 镜头 | {shot.get('lens_mm')}mm |\n"
            f"| 距离 | {shot.get('dist_m')}m |\n| 可见宽 | {shot.get('visible_w_m')}m |\n\n"
            f"出图落 `outputs/{shot.get('first_frame')}`（`SaveImage` 前缀 `meishi/{ffw}`）。\n\n"
            f"**首帧就是构图**：H3 把 `<Picture 1>` 当起点状态、景别基本被沿用，"
            f"所以景别与机位只能在这里定死。")


def _h3_note(scene: dict, shot: dict, wf: str) -> str:
    return (f"# {scene['id']} {shot['id']} · H3 Ref2VA（六段式）\n\n"
            f"**本文件由 `pipeline.py gen S6` 用模板生成，不是手写的。**\n\n"
            f"| 项 | 值 |\n|---|---|\n"
            f"| 后端 | MiniMax H3 **Ref2VA**（一次前向同时出画面＋声音） |\n"
            f"| 画布 | 1376×768 |\n"
            f"| 帧数 | **{shot.get('frames')}** ＝ 17k+5 ✅ |\n"
            f"| 时长 | {shot.get('duration_s')}s @ 24fps |\n"
            f"| 采样 | **4 步** / simple / res_multistep / denoise 1.0 |\n"
            f"| LoRA | `{H3_MODELS['lora']}`（**4 步档**）|\n"
            f"| 参考图 | 只有 `ref_image_0` ＝ `<Picture 1>`，来自 `{shot.get('first_frame')}` |\n\n"
            f"**六段式段序固定**：subject_definitions → summary → retention_analysis →\n"
            f"detailed_description → overall_soundscape → non_diegetic_music。\n\n"
            f"**画风句在 detailed_description 第 0 字，GEO 英文块逐字在内** —— "
            f"这两条由程序拼进去，改提示词前先看 `pipeline/docs/06_审计闸门.md`。")


def cmd_gen(proj: Path, stage_id: str, scene_id: str | None, rounds: int) -> int:
    rules = PA.load_rules(proj)
    scene = pick_scene(proj, rules, scene_id)

    if stage_id == "S7":
        return _gen_verdicts(proj, rules, scene, rounds)

    # S6 走独立路径：**模型只供剧作文本，工作流图由程序拼**（见 build_*_workflow）
    if stage_id == "S6":
        print(f"▶ 自动生成 · S6 写提示词（含首帧工作流）"
              f"（最多 {rounds} 轮，不过就把门禁的错打回给模型重做）")
        return _gen_s6(proj, rules, scene, rounds)

    spec = _gen_spec(stage_id, proj, rules, scene)
    print(f"▶ 自动生成 · {stage_id} {spec['name']}"
          f"（最多 {rounds} 轮，不过就把门禁的错打回给模型重做）")
    errs: list = []
    for i in range(1, rounds + 1):
        ok, res = _gen_once(proj, stage_id, rules, scene, spec["ask"],
                            spec["out"], spec["gate"], errs, i, rounds)
        if ok:
            print(f"\n🎬 {stage_id} 过了（第 {i} 轮）")
            return 0
        if isinstance(res, str):
            print(f"\n⛔ {stage_id} 失败：{res}")
            return 1
        errs = res

    # 记下"跑了 N 轮没过"这件事本身
    fail_file = proj / "review" / f"{stage_id}_生成失败.json"
    fail_file.parent.mkdir(parents=True, exist_ok=True)
    fail_file.write_text(json.dumps({
        "stage": stage_id, "scene": scene["id"], "rounds": rounds,
        "last_errors": errs,
        "_note": "跑满轮数仍未过门禁。**别当它成功**；看 last_errors。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n⛔ {stage_id} 跑满 {rounds} 轮仍未过门禁，已记 {fail_file.name}")
    return 1


def _gen_verdicts(proj: Path, rules: dict, scene: dict, rounds: int) -> int:
    """S7：逐镜让模型读审计包写判定。**判定由程序封存，模型碰不到封条。**"""
    import llm
    done = 0
    for s in (scene.get("t") or {}).get("shots") or []:
        wf = s.get("workflow")
        pf = ROOT / ".work" / "audit" / "packets" / f"{proj.name}.{wf}.packet.json"
        if not pf.exists():
            print(f"⚠️  {s['id']} 没有审计包，先跑 audit-all")
            continue
        ask = (f"下面是镜头 {s['id']} 的审计包。**逐拍核对：戏里写的每一样东西，"
               f"到底进没进这条提示词。**\n\n"
               f"输出判定 JSON（严格照 schema）：\n"
               f'{{"subject":"{wf}","auditor":"model","verdict":"pass 或 fail",'
               f'"summary":"两三句","findings":[{{"id":"F1","level":"error|warn|info",'
               f'"code":"对应机械码或 null","claim":"...","evidence":"...","fix":"..."}}],'
               f'"blocking":["F1"],"waivers":[]}}\n\n'
               f"判据：机械 ERROR **逐条复核**。是真问题就写进 findings；"
               f"确实是误报才写进 waivers 并给 reason。**不许为了让流程过而判 pass。**\n\n"
               f"## 审计包\n{pf.read_text(encoding='utf-8-sig')}")
        vf = proj / "review" / "audits" / f"{wf}.verdict.json"
        vf.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n── {s['id']}  {wf}")
        try:
            v = llm.chat_json([{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": ask}])
        except Exception as exc:                   # noqa: BLE001
            print(f"   ⛔ 模型调用失败：{exc}")
            return 1
        v.setdefault("subject", wf)
        vf.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"   判定 {v.get('verdict')} → {vf.name}（findings "
              f"{len(v.get('findings') or [])}）")
        done += 1
    print(f"\n写了 {done} 份判定。**下一步由程序封存**："
          f"pipeline.py seal-all {proj.name} --scene {scene['id']}")
    return 0


# ══════════════════════════════════════════════════════════════════════
#  审查用的物料清单（给可视化界面用）
# ══════════════════════════════════════════════════════════════════════
def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")


def collect_media(proj: Path, rules: dict, scene: dict) -> dict:
    """把这一场**要看的东西**分组列出来：成片镜头 / 首帧 / 角色资产 / 场景资产 / 画风样张。

    **只列文件、只读尺寸与时长，不做任何判断。** 判断是人的事（规矩 §5.C 第 11 条）。
    每一条都带 `rel`（相对项目根），界面用 `/media?p=<rel>` 取原文件。
    """
    qc = {}
    qf = proj / "review" / f"{scene['id']}_合规检查.json"
    if qf.exists():
        try:
            for c in (json.loads(read(qf)).get("checks") or []):
                qc.setdefault(c.get("shot"), []).append(c)
        except ValueError:
            pass

    def item(p: Path, label: str, **extra) -> dict:
        d = {"label": label, "rel": str(p.relative_to(proj)).replace("\\", "/"),
             "name": p.name, "size": p.stat().st_size, "mtime": _mtime(p),
             "kind": "video" if p.suffix.lower() in (".mp4", ".webm", ".mov") else "image"}
        if d["kind"] == "image":
            sz = PA.image_size(p)
            d["w"], d["h"] = (sz if sz else (None, None))
        else:
            try:
                info = probe_mp4(p)
                d.update({k: info.get(k) for k in
                          ("duration_s", "width", "height", "frames", "fps",
                           "has_audio", "audio_sample_rate", "audio_channels")})
            except Exception:                       # noqa: BLE001
                pass
        d.update(extra)
        return d

    groups: list[dict] = []

    # ① 成片镜头 —— **审查的主战场**
    shots = []
    for s in (scene.get("t") or {}).get("shots") or []:
        sid = s.get("id")
        hits = sorted((proj / "outputs").glob(f"*{sid}*.mp4"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for i, p in enumerate(hits):
            bad = [c for c in qc.get(sid, []) if c.get("result") == "fail"]
            shots.append(item(p, f"{sid}　{s.get('content','')}"
                                 + ("" if i == 0 else f"（旧版 {i}）"),
                              shot=sid, beats=s.get("beats"),
                              expect_frames=s.get("frames"),
                              expect_canvas=rules.get("canvas"),
                              qc_fail=[f"{c['item']}：{c['got']}" for c in bad],
                              qc_pass=sum(1 for c in qc.get(sid, [])
                                          if c.get("result") == "pass"),
                              is_current=(i == 0)))
    if shots:
        groups.append({"id": "shots", "title": "成片镜头（审查主战场）", "items": shots})

    # ② 首帧 —— 画风与身份是它定的
    ff = []
    for s in (scene.get("t") or {}).get("shots") or []:
        sid, name = s.get("id"), (s.get("first_frame") or "")
        cands = []
        if name:
            cands = [proj / "assets" / name, proj / "outputs" / name,
                     proj / "storyboard" / name]
        cands += sorted((proj / "outputs").glob(f"*{sid}*.png"))
        seen = set()
        for p in cands:
            if p.exists() and p not in seen:
                seen.add(p)
                ff.append(item(p, f"{sid} 首帧", shot=sid,
                               registered=bool(name and p.name == name),
                               registered_name=name or None))
    if ff:
        groups.append({"id": "firstframes", "title": "首帧（成片画风由它决定）",
                       "items": ff})

    # ③ 画风样张
    st = [item(p, p.stem) for p in sorted((proj / "outputs").glob("style_*.png"))]
    if st:
        groups.append({"id": "style", "title": "画风样张（选定的是 style_I_H_mature）",
                       "items": st})

    # ④ 角色／场景资产
    for gid, title, d in (("chr", "角色资产", proj / "assets" / "CHR"),
                          ("scn", "场景资产", proj / "assets" / "SCN")):
        if d.is_dir():
            its = [item(p, p.stem) for p in sorted(d.glob("*"))
                   if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if its:
                groups.append({"id": gid, "title": title, "items": its})

    # ⑤ 还没归类的产物，别让东西"看不见"
    known = {i["rel"] for g in groups for i in g["items"]}
    rest = [item(p, p.stem) for p in sorted((proj / "outputs").glob("*"))
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".mp4")
            and str(p.relative_to(proj)).replace("\\", "/") not in known]
    if rest:
        groups.append({"id": "other", "title": "其他产物", "items": rest[:60]})

    return {"scene": scene["id"], "groups": groups,
            "counts": {g["id"]: len(g["items"]) for g in groups},
            "total": sum(len(g["items"]) for g in groups)}


# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="漫剧制作管线（阶段状态机 + 程序兜底）")
    ap.add_argument("cmd", choices=["stages", "scenes", "status", "gate", "verify",
                                    "brief", "seal", "ui", "json", "qc", "run",
                                    "scaffold", "probe", "audit-all", "seal-all",
                                    "gen", "media"])
    ap.add_argument("project")
    ap.add_argument("target", nargs="?", help="阶段 id / 文件（gate/brief/seal/gen 用）")
    ap.add_argument("verdict", nargs="?", help="seal 用：判定 JSON")
    ap.add_argument("--scene", default=None)
    ap.add_argument("--all-scenes", action="store_true",
                    help="批量命令（audit-all / seal-all）跑**全部场次**，"
                         "而不是只跑默认那一场")
    ap.add_argument("--shot", default=None, help="run 用：只跑某一镜")
    ap.add_argument("--rounds", type=int, default=3, help="gen 用：最多打回重做几轮")
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

    if a.cmd == "audit-all":
        return cmd_audit_all(proj, a.scene, a.all_scenes)

    if a.cmd == "seal-all":
        return cmd_seal_all(proj, a.scene, a.all_scenes)

    if a.cmd == "gen":
        if not a.target:
            ap.error("gen 需要阶段 id（S2 / S4 / S7）")
        return cmd_gen(proj, a.target, a.scene, a.rounds)

    if a.cmd == "media":
        rules = PA.load_rules(proj)
        print(json.dumps(collect_media(proj, rules, pick_scene(proj, rules, a.scene)),
                         ensure_ascii=False, indent=2))
        return 0

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
