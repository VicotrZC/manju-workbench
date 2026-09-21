#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模型通道探针 —— **探出这个网关真实接受到什么程度**，别靠猜。

    python tools/probe_llm.py            # 跑全套
    python tools/probe_llm.py tokens     # 只探 max_tokens 天花板

## 为什么需要它

2026-09-21 实测事故：`deepseek-v4.1-flash` 是**推理模型**，思考放在 `reasoning_content`，
但**和正文共用 `max_tokens` 这一个额度**。当时配 16000，模型思考输出了 48063 字符，
把额度吃光：

- 一次是「正文为空、只有 reasoning_content」
- 一次是**JSON 断在半句** —— 表面看像"模型不会写 JSON"，其实是额度不够

**额度上限不能猜。** 猜低了就是截断，猜高了网关直接回 HTTP 400。
所以这个探针逐档上调，把天花板量出来，写进 `llm_config.json`。

## 实测记录（2026-09-21）

| max_tokens | 结果 |
|---|---|
| 8000 / 32000 / 64000 | ✅ 接受 |
| 96000 / 128000 / **200000** | ✅ 接受 ← **当前配置取这个** |
| 1000000 | ❌ `HTTP 400 invalid_request_error` |

`max_tokens` 是**上限不是配额** —— 模型思考完就停，给大了不会白烧钱。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def probe_tokens(ladder: list[int]) -> int:
    """逐档上调 max_tokens，找出网关接受的最大值。"""
    cfg = llm.load_config()
    print(f"通道 {cfg['base_url']}　模型 {cfg['model']}")
    print(f"当前配置 max_tokens = {cfg['max_tokens']}\n")
    best = None
    for mt in ladder:
        try:
            t0 = time.time()
            out = llm.chat([{"role": "user", "content": "只回复两个字：通了"}],
                           max_tokens=mt, timeout=180)
            print(f"  max_tokens={mt:8d}  ✅ {time.time()-t0:5.1f}s  → {out.strip()[:30]}")
            best = mt
        except llm.LLMError as e:
            print(f"  max_tokens={mt:8d}  ❌ {str(e)[:160]}")
    if best is None:
        print("\n❌ 全部档位都失败 —— 先查密钥与 base_url（`llm.py config` / `llm.py models`）")
        return 1
    print(f"\n👉 网关接受的最大档 = **{best}**")
    if cfg["max_tokens"] != best:
        print(f"   当前配置是 {cfg['max_tokens']}。"
              f"{'（比天花板小，可能截断）' if cfg['max_tokens'] < best else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="模型通道探针")
    ap.add_argument("what", nargs="?", default="all", choices=["all", "tokens"])
    a = ap.parse_args()

    if a.what in ("all", "tokens"):
        # 逐档上调。16000 是历史事故点（会截断），后面一路顶到网关拒收为止。
        # ⚠️ 探针**不要传会触发自愈折半的档**，否则量到的是折半后的值不是天花板。
        rc = probe_tokens([16000, 64000, 200000, 400000, 600000, 800000, 1000000])
    else:                                          # pragma: no cover
        rc = 0

    if a.what == "all":
        print("\n── 顺带跑一遍通道自检 ──")
        try:
            t0 = time.time()
            llm.chat([{"role": "user", "content": "只回复两个字：通了"}], max_tokens=2000)
            print(f"  ✅ 通道正常（{time.time()-t0:.1f}s）")
        except llm.LLMError as e:
            print(f"  ❌ {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
