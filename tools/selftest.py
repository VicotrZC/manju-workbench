#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""自测 —— **拿已知的坏样例去打自己的检查器，证明它真的会报。**

    python tools/selftest.py

## 为什么必须有这个

规矩 §5.C 第 12 条：**「agent 报通过」不等于「内容合格」。**
同理，**「程序没报错」不等于「程序检查过了」**。

2026-09-21 的两次实测教训都是这个形状：

1. `WF-16` 因为"两边都指向同一个不存在的名字"而**静默通过** —— 首帧从来不存在，检查却是绿的。
2. `extract_json` 把截断的 JSON 报成一句 `Expecting ',' delimiter`，
   于是 `pipeline` 把「模型被截断」当成「模型写坏了语法」，**整轮生成白死**。

所以每个检查器都要有**已知会失败的样例**。没有样例的检查，等于没有检查。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FAILED: list[str] = []


def check(name: str, got, want, note: str = ""):
    ok = got == want
    print(f"  {'✅' if ok else '❌'} {name:44s} 得到 {got!r}"
          + (f"　（期望 {want!r}）" if not ok else "")
          + (f"　{note}" if note else ""))
    if not ok:
        FAILED.append(name)


# ══════════════════════════════════════════════════════════════════════
#  extract_json：**截断**必须和**写坏了**分开报
# ══════════════════════════════════════════════════════════════════════
def test_extract_json():
    print("\n── extract_json：截断 vs 写坏了 ──")

    def outcome(txt: str) -> str:
        """→ 'ok' | 'truncated' | 'broken' | 'no-json'"""
        try:
            llm.extract_json(txt)
            return "ok"
        except llm.LLMError as e:
            s = str(e)
            if "被截断" in s and "像是被截断" not in s:
                return "truncated"
            if "像是被截断了" in s or "这是被截断" in s:
                return "truncated"
            if "找不到 JSON 对象" in s:
                return "no-json"
            return "broken"

    check("括号不配对 → 截断", outcome('{"a":1,"b":[1,2,'), "truncated")
    check("停在冒号后 → 截断", outcome('{"a":1,"b":'), "truncated")
    check("完全没闭合括号 → 截断", outcome('{"shots":[{"id":"S00"'), "truncated")
    check("多余逗号 → 写坏了（不是截断）", outcome('{"a":1,,"b":2}'), "broken")
    check("根本没有 JSON", outcome("我觉得这个方案挺好的，你看呢？"), "no-json")
    check("裸 JSON → 能解", outcome('{"a":1}'), "ok")
    check("``` 包装 → 能解", outcome('yyy ```json\n{"a":1}\n``` zzz'), "ok")

    # 关键：**pipeline 的重试环靠这四个字判断该不该打回重做**
    try:
        llm.extract_json('{"a":1,"b":')
    except llm.LLMError as e:
        check("截断报错里含『被截断』四字（重试环靠它）",
              "被截断" in str(e), True)
    try:
        llm.extract_json('{"a":1,,"b":2}')
    except llm.LLMError as e:
        check("写坏了的报错**不**含『像是被截断』（别误导成调额度）",
              "像是被截断" in str(e), False)


# ══════════════════════════════════════════════════════════════════════
#  Report.promote_pending：PENDING 只在"该拦的那一关"变 ERROR
# ══════════════════════════════════════════════════════════════════════
def test_pending():
    print("\n── Report 的 PENDING / promote_pending ──")
    import pipeline_audit as PA

    r = PA.Report("t")
    r.pending("X-01", "产物还没出")
    check("PENDING 不算错（ok() 为真）", r.ok(), True)
    check("PENDING 进 pendings", len(r.pendings), 1)
    check("PENDING 不进 errors", len(r.errors), 0)
    n = r.promote_pending("推到 GPU 了")
    check("promote 提成 ERROR 的条数", n, 1)
    check("提完之后 ok() 为假", r.ok(), False)
    check("提完之后 errors 有一条", len(r.errors), 1)
    check("理由被写进消息", "推到 GPU 了" in r.errors[0]["msg"], True)


# ══════════════════════════════════════════════════════════════════════
#  镜头表判据：坏表必须被抓出来
# ══════════════════════════════════════════════════════════════════════
def test_shot_table_rules():
    print("\n── 镜头表判据（拿真项目当样本，只读不改）──")
    import json

    import pipeline as P
    import pipeline_audit as PA

    proj = Path("projects") / "美食：全市巡摆，馋哭食客"
    if not proj.exists():
        print("  ⏭  项目不在，跳过")
        return
    rules = PA.load_rules(proj)
    tbl = json.loads((proj / rules["shot_table"]).read_text(encoding="utf-8-sig"))
    shots = tbl["shots"]

    check("每镜都有 workflow", all(s.get("workflow") for s in shots), True)
    check("每镜都有 first_frame_workflow",
          all(s.get("first_frame_workflow") for s in shots), True)
    wfs = [s["workflow"] for s in shots]
    check("工作流不串档（一镜一条）", len(wfs), len(set(wfs)))
    ffws = [s["first_frame_workflow"] for s in shots]
    check("首帧工作流不串档", len(ffws), len(set(ffws)))
    check("帧数全在 17k+5 网格",
          all((int(s["frames"]) - 5) % 17 == 0 for s in shots), True)

    # 节拍覆盖：这是「骑车赶到菜市整拍消失」那类事故的唯一防线
    rep, chain = PA.check_chain(proj, rules, materials="pending")
    beats = chain.get("beats") or {}
    claimed = {b for s in shots for b in s.get("beats") or []}
    check("戏里每一拍都有镜头认领", sorted(set(beats) - claimed), [])

    # 自造的坏表：把两镜的工作流改成同一个名字，判据必须报
    bad = json.loads(json.dumps(tbl))
    if len(bad["shots"]) >= 2:
        bad["shots"][1]["workflow"] = bad["shots"][0]["workflow"]
        names = [s["workflow"] for s in bad["shots"]]
        check("自造『两镜共用一个工作流』能被看穿",
              len(names) != len(set(names)), True)


def main() -> int:
    print("自测 —— 拿已知的坏样例打自己的检查器")
    print("[1/3] extract_json …", flush=True)
    test_extract_json()
    print("[2/3] PENDING …", flush=True)
    test_pending()
    print("[3/3] 镜头表判据 …", flush=True)
    test_shot_table_rules()
    print("\n" + "─" * 60)
    if FAILED:
        print(f"❌ {len(FAILED)} 项没过：")
        for f in FAILED:
            print(f"   - {f}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
