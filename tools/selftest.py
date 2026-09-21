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
    check("本场戏里每一拍都有镜头认领", sorted(set(beats) - claimed), [])

    # 自造的坏表：把两镜的工作流改成同一个名字，判据必须报
    bad = json.loads(json.dumps(tbl))
    if len(bad["shots"]) >= 2:
        bad["shots"][1]["workflow"] = bad["shots"][0]["workflow"]
        names = [s["workflow"] for s in bad["shots"]]
        check("自造『两镜共用一个工作流』能被看穿",
              len(names) != len(set(names)), True)


# ══════════════════════════════════════════════════════════════════════
#  多场次判据（**负向样例：故意弄坏，证明它真的会报**）
# ══════════════════════════════════════════════════════════════════════
def test_multi_scene():
    """拆场次后新增的判据：BEAT-01（本场漏拍）/ BEAT-03（登记错）/ BEAT-04（越界）。

    **为什么必须用负向样例**：`pipeline.py gate` 说"通过"时，
    分不清是**真的对**还是**检查没跑到**。2026-09-21 的 `WF-16` 就是静默通过。
    所以这里拿真项目复制一份到临时目录，**故意弄坏**，看判据会不会响。
    """
    print("\n── 多场次：BEAT-01 / BEAT-03 / BEAT-04（负向样例）──")
    import json
    import shutil
    import tempfile

    import pipeline_audit as PA

    src = Path("projects") / "美食：全市巡摆，馋哭食客"
    if not src.exists():
        print("  ⏭  项目不在，跳过")
        return

    need = ["audit_rules.json", "项目卡.md"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "proj"
        tmp.mkdir()
        for f in need:
            if (src / f).exists():
                shutil.copy2(src / f, tmp / f)
        for sub in ("script", "storyboard", "assets", "workflows"):
            if (src / sub).is_dir():
                shutil.copytree(src / sub, tmp / sub)
        rules = PA.load_rules(tmp)

        # ⚠️ **把工作流登记换成不存在的假名**：这一节测的是**节拍覆盖判据**，
        # 不该被"某个工作流的画风句占比"这种完全无关的问题拖成 FAIL。
        # 假名而不是 `null` —— `workflow` 是必填字段（SHOT-01 会报空），
        # 填假名则字段在、但不会真去加载文件。
        # 2026-09-21 实测：盘上有一条画风占比不过的工作流，负向样例就整体报错了 ——
        # **测试的失败原因必须指向它要测的那件事**，否则读的人会去查错地方。
        for tf in (tmp / "storyboard").glob("*_镜头表.json"):
            t = json.loads(tf.read_text(encoding="utf-8-sig"))
            for s in t.get("shots") or []:
                s["workflow"] = f"_T_{s.get('id')}_h3"
            tf.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")

        def codes(table_rel: str, mutate=None) -> set[str]:
            """改坏一份镜头表，跑链，返回报出来的 code 集合。

            ⚠️ **必须把 `table_rel` 传给 check_chain** —— 不给的话它用项目级
            `shot_table`（SCN-01 那一份），改 SCN-02 根本不会被读到。
            （2026-09-21：本测试第一版就漏了这个参数，4 条负向样例全部"没报"，
              差点被当成"判据坏了"。**测试自己写错，比判据坏了更难发现。**）
            """
            t = json.loads((tmp / table_rel).read_text(encoding="utf-8-sig"))
            if mutate:
                mutate(t)
            (tmp / table_rel).write_text(json.dumps(t, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
            rep, _ch = PA.check_chain(tmp, rules, materials="pending",
                                      table_rel=table_rel)
            return {i["code"] for i in rep.items if i["level"] == "ERROR"}

        # ── 原点：不动它，**节拍覆盖类判据不该报任何错** ──
        # ⚠️ 断言的是"没有 BEAT-* 的错"，不是"一个错都没有"。
        # 这一节测的是节拍覆盖；工作流内容／首帧／资产图各自有各自的工序与测试，
        # 它们正在返工时不该把这条判据的测试染红（**失败原因必须指向被测的那件事**）。
        c0 = codes("storyboard/SCN02_镜头表.json")
        check("原样：没有任何 BEAT-* 的错",
              sorted(x for x in c0 if x.startswith("BEAT-")), [])

        # ── BEAT-01：本场那一拍没人认领 ──
        c = codes("storyboard/SCN02_镜头表.json",
                  lambda t: [s.update(beats=[]) for s in t["shots"]])
        check("删掉 SCN-02 的认领 → BEAT-01 报出来", "BEAT-01" in c, True)

        # ── BEAT-04：认领了不属于本场的拍（把摊内的 B2 塞给空街场）──
        c = codes("storyboard/SCN02_镜头表.json",
                  lambda t: [s.update(beats=["B2"]) for s in t["shots"]])
        check("SCN-02 认领 B2（别场的拍）→ BEAT-04 报出来", "BEAT-04" in c, True)

        # ── BEAT-02：认领了戏里根本不存在的拍 ──
        c = codes("storyboard/SCN02_镜头表.json",
                  lambda t: [s.update(beats=["B9"]) for s in t["shots"]])
        check("SCN-02 认领不存在的 B9 → BEAT-02 报出来", "BEAT-02" in c, True)

        # ── BEAT-03：beat_scope 登记的拍在该场戏里不存在 ──
        def break_scope(t):
            pass
        bad_rules = json.loads(json.dumps(rules))
        bad_rules["beat_scope"]["SCN-02"]["beats"] = ["B7"]
        (tmp / "audit_rules.json").write_text(
            json.dumps(bad_rules, ensure_ascii=False, indent=2), encoding="utf-8")
        rep3, _ = PA.check_chain(tmp, bad_rules, materials="pending",
                                 table_rel="storyboard/SCN02_镜头表.json")
        c3 = {i["code"] for i in rep3.items if i["level"] == "ERROR"}
        check("beat_scope 登记了戏里没有的拍 → BEAT-03 报出来", "BEAT-03" in c3, True)

        # ── 恢复 rules，验「一场漏读另一场」不会发生 ──
        (tmp / "audit_rules.json").write_text(
            json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        tables = PA.all_shot_tables(tmp, rules)
        check("两个场次的镜头表都能被发现", len(tables), 2)
        # 按工作流反查归属：**用替身名测查表逻辑**，不依赖盘上有没有真工作流
        # （真工作流可能因为内容问题正在返工，那不该让这条判据的测试变红）
        wf_scene = PA.table_for_workflow(tmp, rules, "_T_S00_h3")
        check("能按工作流反查它属于哪一场（SCN-02）",
              (wf_scene or "").endswith("SCN02_镜头表.json"), True)

        # ── 跨场次覆盖：**拆场次最容易出的新事故是"某一拍落在两场之间的缝里"** ──
        # 每场各自「不漏自己的拍」由 BEAT-01 管；但没有任何一条判据管
        # 「两场加起来是不是把戏全包了」。这里替它把住。
        all_beats: set[str] = set()
        for rel in tables:
            _r, ch = PA.check_chain(tmp, rules, materials="pending", table_rel=rel)
            all_beats |= set((ch.get("beats") or {}).keys())
        scope_union = {b for sid in (rules.get("beat_scope") or {})
                       for b in PA.beat_scope(rules, sid)}
        check("两场合起来覆盖了全部已登记的节拍",
              sorted(scope_union - all_beats), [])


# ══════════════════════════════════════════════════════════════════════
#  资产接线判据 CHAIN-03（**负向样例：纯 t2i 的首帧必须被拦下**）
# ══════════════════════════════════════════════════════════════════════
def test_asset_wiring():
    """用户 2026-09-21 拍板「首帧必须用参考图，不然漂移非常严重」，
    `CHAIN-03` 就是那句话的机器判据。

    **这条测试的由来**（用户实测发现，不是我自己想到的）：

    > 角色身份卡不用、电动车的资产没有生成，你就凭空生成了，而且还过了门禁。

    根因：在 `CHAIN-03` 之前，**没有任何检查器问过**
    「镜头声明了资产，工作流到底有没有把资产读进去」——
    审计只审提示词文本，于是「用嘴说用了 CHR-01」也算过。
    """
    print("\n── 资产接线：CHAIN-03（负向样例）──")
    import json
    import shutil
    import tempfile

    import pipeline_audit as PA

    src = Path("projects") / "美食：全市巡摆，馋哭食客"
    if not src.exists():
        print("  ⏭  项目不在，跳过")
        return

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "proj"
        tmp.mkdir()
        for f in ("audit_rules.json", "项目卡.md"):
            if (src / f).exists():
                shutil.copy2(src / f, tmp / f)
        # ⚠️ **`script/` 必须一起复制。** 2026-09-21 实测踩到：
        # 少了它 → `check_chain` 报 CHAIN-01「剧本层文件缺失」→ **chain 的 shots 变成空表**
        # → `check_workflow` 认不出这是哪一镜 → `is_first_frame_wf` 为假
        # → **CHAIN-03 整条静默不跑**，测试报"没抓到"，看起来像判据坏了。
        # 又一次「测试自己写错，比判据坏了更难发现」（见 test_multi_scene 的同类教训）。
        for sub in ("script", "storyboard", "workflows", "assets"):
            if (src / sub).is_dir():
                shutil.copytree(src / sub, tmp / sub)
        rules = PA.load_rules(tmp)
        rel = PA.table_for_workflow(tmp, rules, "FF_EP02SC02_S00")
        _crep, chain = PA.check_chain(tmp, rules, materials="pending", table_rel=rel)

        def c3(rules_now=None):
            rep, _ = PA.check_workflow(tmp, "FF_EP02SC02_S00", rules_now or rules, chain)
            return [i for i in rep.items if i["code"] == "CHAIN-03"]

        # ── 负向样例 1：真实那条工作流是纯 t2i（没有 LoadImage）──
        got = c3()
        check("纯 t2i 首帧 → 「没有任何参考图输入」报出来",
              any("没有任何参考图输入" in i["msg"] for i in got), True)

        # ── 负向样例 2：声明了、但没登记进锁定件的资产 ──
        # （PRP-02 小电驴 / SCN-02 空街场景 —— 两个资产图都还没出）
        check("未登记的资产 PRP-02 → 报出来",
              any("PRP-02" in i["msg"] and "没有登记" in i["msg"] for i in got), True)
        check("未登记的资产 SCN-02 → 报出来",
              any("SCN-02" in i["msg"] and "没有登记" in i["msg"] for i in got), True)

        # ── 正向样例：把参考图接进去，「没有任何参考图输入」必须消失 ──
        # **只测这一条会消失**，不断言"一个错都没有" ——
        # 工作流内容本身的问题不该把这条判据的测试染红
        # （失败原因必须指向被测的那件事）。
        wf_p = tmp / "workflows" / "FF_EP02SC02_S00.json"
        wf = json.loads(wf_p.read_text(encoding="utf-8"))
        wf["nodes"].append({"id": 900, "type": "LoadImage",
                            "widgets_values": ["CHR01_body_neutral_00004__nohead.png", "image"]})
        wf_p.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
        got2 = c3()
        check("接进参考图后 → 「没有任何参考图输入」消失",
              any("没有任何参考图输入" in i["msg"] for i in got2), False)
        check("读的正是 CHR-01 的图 → 不再报「CHR-01 没被读」",
              any("CHR-01" in i["msg"] and "没有读" in i["msg"] for i in got2), False)

        # ── 负向样例 3：登记了资产，但一张图都没有（files 为空）──
        # 这是最坏的一种静默：清单写了 why、S5 记了待产出，**唯独门禁说通过**。
        r2 = json.loads(json.dumps(rules))
        r2.setdefault("props", {})["PRP-02"] = {"name": "小电驴（闫清代步电动车）", "files": []}
        (tmp / "audit_rules.json").write_text(
            json.dumps(r2, ensure_ascii=False, indent=2), encoding="utf-8")
        got3 = c3(r2)
        check("登记了但 files 为空 → 记 PENDING（「还没做」不是「做错了」）",
              any(i["level"] == "PENDING" and "PRP-02" in i["msg"] for i in got3), True)
        crep2, _ = PA.check_chain(tmp, r2, materials="error", table_rel=rel)
        check("CHAIN-02：files 为空 → 报「一张资产图都没有」",
              any(i["code"] == "CHAIN-02" and "一张资产图都没有" in i["msg"]
                  for i in crep2.items), True)


def test_license():
    """模型许可证判据（LIC-01/02/03）。

    ⚠️ **这个测试是为了钉住一个真发生过的 bug**（2026-09-21，LIC-03 写完第一次真跑就抓到）：

    第一版把 `blocked[].match` **直接当正则**用 —— 而 `qwen_image_2.1` 里的
    **`.` 在正则里是"任意字符"**，于是它把 **`qwen_image_2512` 也判成受限模型**，
    在**每一条首帧工作流上误报 LIC-03**。

    这类误报的后果不是"多一条噪音"，是**人会去把检查关掉**。所以这里**两个方向都要钉**：
    ① 不能把前缀相同的可商用模型误判成受限（误报）；② 真受限的必须抓到（漏报）。
    """
    print("\n── 许可证登记 LIC-01/02/03 ──")
    import json

    import pipeline_audit as audit

    proj = Path("projects") / "美食：全市巡摆，馋哭食客"
    if not proj.exists():
        print("  ⏭  项目不在，跳过")
        return

    reg = audit._license_registry()
    check("登记表读得到", reg is not None and bool(reg.get("models")), True)

    # ── 登记表必须**恰好覆盖**项目里真实加载的模型文件 ──
    # ⚠️ 这里**不写死条目数**：写死的话远端加一条工作流、本地就变红，
    # 而真正该问的是「有没有谁在用没登记的模型」。改成动态比对 ——
    # 多一个少一个都要报，且报出来的是**文件名**，不是一个数字。
    known = {m["file"] for m in (reg or {}).get("models") or []}
    used: set[str] = set()
    for wf_file in (proj / "workflows").glob("*.json"):
        try:
            wf = json.loads(wf_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in wf.get("nodes", []):
            if n.get("type") in audit.LICENSE_LOADER_NODES:
                wv = n.get("widgets_values") or []
                if wv and isinstance(wv[0], str) and wv[0].strip():
                    used.add(wv[0].strip())
    check("工作流里加载的模型全部有登记（差谁列在下面）", sorted(used - known), [])
    check("登记表里没有僵尸条目（登了没人用）", sorted(known - used), [])
    check("登记条目数 = 实际使用数", len(known), len(used))

    # ── ① 误报防线：这些**没被禁**，一个都不许命中 ──
    for f in ("qwen_image_2512_fp8_e4m3fn.safetensors",
              "qwen_image_edit_2511_fp8mixed.safetensors",
              "qwen_image_vae.safetensors",
              "Qwen-Image-2512-Lightning-8steps-V1.0-bf16.safetensors",
              "qwen_2.5_vl_7b_fp8_scaled.safetensors",
              "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
              "minimax_h3_ref2va_pruned_int8_convrot.safetensors"):
        check(f"不误报受限：{f[:38]}", audit._blocked_match(reg, f) is None, True)

    # ── ② 漏报防线：真受限的几种写法都要抓到 ──
    for f in ("qwen_image_2.1_fp8.safetensors", "Qwen-Image-2.1.safetensors"):
        check(f"抓得到受限：{f}", audit._blocked_match(reg, f) is not None, True)

    # ── ③ 端到端：拿真工作流的节点列表跑一遍 ──
    # 视频工作流：5 个模型全登记 → **不许有 LIC-01**，但 H3 那条要有 LIC-02
    vwf = json.loads((proj / "workflows" / "EP02SC02_S00_h3.json")
                     .read_text(encoding="utf-8"))
    r = audit.Report("t")
    hit = audit.check_license(r, vwf.get("nodes", []))
    check("视频工作流：登记表覆盖 5 个模型", hit["checked"], 5)
    check("视频工作流：没有未登记的（LIC-01 不该出现）", hit["unregistered"], [])
    check("视频工作流：H3 系 4 个模型报『有条件』", len(hit["conditional"]), 4)
    check("视频工作流：没有受限模型", hit["blocked"], [])

    # ④ 未登记的模型必须被 LIC-01 抓到（**这条才是这张表存在的理由**）
    fake = [{"type": "UNETLoader", "widgets_values": ["some_unregistered_model.safetensors"]}]
    r2 = audit.Report("t")
    hit2 = audit.check_license(r2, fake)
    check("未登记的模型 → LIC-01", any(i["code"] == "LIC-01" for i in r2.items), True)
    check("未登记的模型 → 算 ERROR（拦提交）", len(r2.errors), 1)

    # ⑤ 受限模型必须被 LIC-03 抓到，且是 ERROR
    #    ⚠️ 同时钉住「**一条根因只报一条错**」：命中禁区就短路，不再叠一条 LIC-01。
    #    第一版没短路，于是同一个模型报出 LIC-03 + LIC-01 两条 ERROR，
    #    而 LIC-01 的"去补登记"建议是**错的**（补登记等于把禁区模型合法化）。
    r3 = audit.Report("t")
    audit.check_license(r3, [{"type": "UNETLoader",
                              "widgets_values": ["qwen_image_2.1_fp8.safetensors"]}])
    check("受限模型 → LIC-03", any(i["code"] == "LIC-03" for i in r3.items), True)
    check("受限模型 → 算 ERROR", len(r3.errors), 1)
    check("受限模型 → 不叠报 LIC-01（一条根因一条错）",
          any(i["code"] == "LIC-01" for i in r3.items), False)
    check("受限模型 → LIC-02 也不该出现",
          any(i["code"] == "LIC-02" for i in r3.items), False)


def main() -> int:
    print("自测 —— 拿已知的坏样例打自己的检查器")
    print("[1/6] extract_json …", flush=True)
    test_extract_json()
    print("[2/6] PENDING …", flush=True)
    test_pending()
    print("[3/6] 镜头表判据 …", flush=True)
    test_shot_table_rules()
    print("[4/6] 多场次判据（负向样例）…", flush=True)
    test_multi_scene()
    print("[5/6] 资产接线 CHAIN-03（负向样例）…", flush=True)
    test_asset_wiring()
    print("[6/6] 许可证登记 LIC（含误报防线）…", flush=True)
    test_license()
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
