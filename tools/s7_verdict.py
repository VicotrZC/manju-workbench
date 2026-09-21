#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S7 的**审计提问稿** —— 让模型读审计包、写判定 JSON。

    python tools/s7_verdict.py <项目名> <工作流名> [--video]

## 为什么把它从临时脚本提升成正式文件

2026-09-21：我原来把这段提问写在 `.work/` 下的临时脚本里，每次跑完就删。
后果是**审计的判据不可追溯** —— 判定文件里只留了结论，
"当时到底问了模型什么"没有任何地方能查到、能 diff。

审计提问稿就是**审计合同的一半**（另一半是机械判据）。
它必须进 git：改了它，前后的判定才可比。

## 两条必须写进提问稿的项目事实（**模型看不到文件系统之外的约定**）

1. **t2i 提示词用的取景句是压缩版**（`tools/pipeline.py` 的 `framing_t2i`），
   h3 用的才是 `framing_en` 原文。不告诉它，它会把合法的压缩判成"取景句没原样进入"。
2. **首帧是静帧**：台词落点、帧数、时长、防跳轴都不属于它。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm        # noqa: E402
import pipeline as P   # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]

#: 系统提示：**不许为了让流程过而判 pass**
SYS = P.SYSTEM_PROMPT

#: 首帧（t2i 静帧）的判据说明
FF_NOTE = """这是一条**首帧工作流**（t2i 静帧）：它只决定**构图、景别、画风与脸**。

**它不负责这些 —— 看到相关内容判 info 即可，不要写进 findings：**
- 台词／VO 的落点（`<d>…</d>`）—— 那是视频工作流的事（静帧没有说话这回事）
- 帧数（17k+5）、时长、语音密度
- 防跳轴句、GEO 英文块的逐字内嵌 —— GEO 那块长英文只进视频工作流；
  首帧 t2i 塞进去会把画风句占比打到 3%，与画风闸门直接互斥
- `SHOT-02`（首帧图还没出）—— 那张图正是这条工作流要去跑的

**它负责这些，必须逐条核：**
- **取景**：画面里有几个人、谁在哪、朝向哪、景别与机位
- **画风句**：是否在描述段第 0 字、占比是否 ≥ 20%（t2i 下限）
- **身份锚**：出场角色的签名标记英文原文在不在
- **正向否定锁**：造型锁（如 `clean-shaven`）在不在正向里
- **画面文字**：有没有声明画面无字

⚠️ **t2i 的取景句是压缩版，这是设计，不是缺陷。**
上游 `framing_en` 是给 h3 的（要求 `<Shot 1>` 后 400 字内出现），可以写得细；
t2i 描述段有硬预算（画风句 100 字 ÷ 下限 20% ＝ 500 字上限），放不下整句。
`tools/pipeline.py` 的 `framing_t2i` 会**只删冗余限定词与固定短语、分句一个不删**。
→ 判「取景句是否原样进入」时，请比对**分句与构图信息是否齐全**，
  而不是逐字比对 —— 逐字比对必然报错，那是判据错位。"""

#: 视频（H3 六段式）的判据说明
VIDEO_NOTE = """这是一条**视频工作流**（H3 六段式）。**全部都要核：**
- **台词保真**：戏里写的**每一句对白与 VO 原文**都要落在某个 `<d>[Chinese] …</d>` 里，
  一句不落；且照官方写法 `(S1)` 标说话人。
- **GEO 英文块**是否逐字在内；**画风句**是否在 `detailed_description` 第 0 字。
- **取景句**是否出现在 `[Shot 1]` 之后（前 400 字内）。
- **禁字幕句** `No subtitles, captions or on-screen text appear at any point.` 在不在。
- **帧数**是否 17k+5、是否与分镜表登记值一致；**画布** 1376×768。
- **语音密度**：这一镜的时长装不装得下这一拍的字数（口径 5.5 汉字/秒）。
- **防跳轴句**、采样档位与 LoRA 是否成对。"""


def build_ask(packet: dict, wf_name: str, is_video: bool) -> str:
    note = VIDEO_NOTE if is_video else FF_NOTE
    return f"""下面是工作流 `{wf_name}` 的审计包。**逐条核对：这一镜要的东西到底进没进这条提示词。**

{note}

输出判定 JSON（严格照 schema，只输出 JSON）：
{{
  "subject": "{wf_name}",
  "auditor": "model",
  "verdict": "pass 或 fail",
  "summary": "两三句",
  "findings": [{{"id": "F1", "level": "error|warn|info", "code": "对应机械码或 null",
                 "claim": "…", "evidence": "…", "fix": "…"}}],
  "blocking": ["F1"],
  "waivers": [{{"code": "被豁免的机械码", "reason": "为什么是误报"}}]
}}

判据：
- 机械 ERROR **逐条复核**。是真问题就写进 findings；确实是误报才写进 waivers 并给 reason。
- **不许为了让流程过而判 pass**（规矩 §5.C 第 12 条）。
- **画面构图上的歧义也要报**：如果提示词可能被理解成「同一个人出现两次」
  「凭空多出一个前景人物」「道具悬空」「画面里出现本镜不该有的东西」，
  那是真问题 —— 判据是**上游（镜头表／资产清单／戏）说了什么，提示词有没有说清**。
- 判 findings 时请分清**「提示词写错了」**与**「上游本身就这么写的」**：
  后者该报成对上游的意见，不要算成提示词缺陷。

## 审计包
{json.dumps(packet, ensure_ascii=False, indent=2)}"""


def main() -> int:
    ap = argparse.ArgumentParser(description="S7 审计提问稿：读审计包 → 写判定")
    ap.add_argument("project")
    ap.add_argument("workflow")
    ap.add_argument("--video", action="store_true", help="这是视频工作流（默认按首帧静帧判）")
    a = ap.parse_args()

    proj = ROOT / "projects" / a.project
    if not proj.is_dir():
        raise SystemExit(f"❌ 项目不在：{proj}")
    pf = ROOT / ".work" / "audit" / "packets" / f"{a.project}.{a.workflow}.packet.json"
    if not pf.exists():
        raise SystemExit(f"❌ 审计包不在：{pf}\n先跑："
                         f"python tools/pipeline_audit.py preflight {a.project} {a.workflow}")
    packet = json.loads(pf.read_text(encoding="utf-8-sig"))

    print(f"请求模型判定（{a.workflow}，{'视频' if a.video else '首帧'}，"
          f"审计包 {pf.stat().st_size} B）…")
    v = llm.chat_json([{"role": "system", "content": SYS},
                       {"role": "user", "content": build_ask(packet, a.workflow, a.video)}])
    v.setdefault("subject", a.workflow)
    v["auditor"] = "model"
    v["_ask"] = "tools/s7_verdict.py"
    out = proj / "review" / "audits" / f"{a.workflow}.verdict.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"判定 {v.get('verdict')} → {out.relative_to(ROOT)}"
          f"（findings {len(v.get('findings') or [])}，waivers {len(v.get('waivers') or [])}）")
    for f in (v.get("findings") or []):
        print(f"  [{f.get('level')}] [{f.get('code')}] {str(f.get('claim'))[:120]}")
    return 0 if v.get("verdict") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
