#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模型通道 —— **程序直接调 API，不 shell 出去叫任何 CLI**。

    python tools/llm.py ping                 # 验通道（发一句最短的话）
    python tools/llm.py ask "你好"            # 手工问一句
    python tools/llm.py config               # 看当前配置（**不打印密钥**）

## 为什么要这个文件

2026-09-21 用户纠正：**「模型负责生成和审查，执行面交给电脑」**。
我一度打算在程序里 `claude -p` 去叫一个 agent CLI —— 那是错的：
额度不可控、行为不可控，而且根本不是"程序调模型"。

正确的分工是：

| 谁 | 干什么 |
|---|---|
| **模型（HTTP API）** | 生成（分镜／提示词／资产清单）与审查（判定） |
| **本程序** | 构图、拼提示词、发请求、取回结果、**跑门禁** |
| **`tools/run.py`** | 连云机 ComfyUI，推工作流、轮询、下载产物 |

## 配置（两个文件，**密钥永不进 git**）

`llm_config.json`（**进 git**，没有秘密）：

    {
      "base_url": "https://api.deepseek.com/v1",
      "model": "deepseek-chat",
      "temperature": 0.3,
      "max_tokens": 8000,
      "timeout_s": 600
    }

密钥按这个顺序找（**第一个找到的就算**）：

1. 环境变量 `LLM_API_KEY`
2. 仓库根的 `llm_key.txt`（`.gitignore` 已挡）

**任何 OpenAI 兼容的端点都能用** —— DeepSeek、MiniMax、通义、本地 vLLM／Ollama 都行，
只要 `base_url` 指向它的 `/v1`。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "llm_config.json"
KEY_FILE = ROOT / "llm_key.txt"          # .gitignore 挡着
QUEUE = ROOT / ".work" / "llm_queue"     # file 后端的收件箱

DEFAULTS = {
    # OpenCode Zen：OpenAI 兼容网关（地址已核实，见 pipeline/docs/07 §五）
    "base_url": "https://opencode.ai/zen/v1",
    "model": "deepseek-v4-flash-free",
    "backend": "api",          # api = 直接发 HTTP；file = 写进队列等外部填答
    "temperature": 0.3,
    "max_tokens": 8000,
    "timeout_s": 600,
}


class LLMError(RuntimeError):
    pass


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
        except ValueError as exc:
            raise LLMError(f"{CONFIG_FILE.name} 不是合法 JSON：{exc}") from None
    return cfg


def api_key() -> str:
    """按顺序找密钥。**找到了也不回显。**"""
    k = os.environ.get("LLM_API_KEY", "").strip()
    if k:
        return k
    if KEY_FILE.exists():
        k = KEY_FILE.read_text(encoding="utf-8-sig").strip()
        if k:
            return k
    raise LLMError(
        "找不到模型密钥。二选一：\n"
        f"  ① 把密钥写进 {KEY_FILE}（一行，不要引号；.gitignore 已挡）\n"
        "  ② 设环境变量 LLM_API_KEY\n"
        f"  配置（base_url / model）在 {CONFIG_FILE.name}")


def _headers(key: str) -> dict:
    """请求头。

    ⚠️ **User-Agent 不能省。** urllib 默认发 `Python-urllib/3.x`，
    OpenCode Zen 前面的 Cloudflare 会直接 403（实测 `error code: 1010`，
    那是按浏览器签名拦的，跟密钥无关）。
    """
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "manju-workbench/1.0 (+tools/llm.py)",
        "Accept": "application/json",
    }


def _post(url: str, payload: dict, key: str, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:900]
        raise LLMError(f"HTTP {e.code} from {url}\n{body}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"连不上 {url}：{e.reason}") from None


def chat(messages: list[dict], *, temperature=None, max_tokens=None,
         timeout=None, retries: int = 2) -> str:
    """发一轮对话，返回正文。

    **后端可插拔**（`llm_config.json` 的 `backend`）：

    | backend | 干什么 | 什么时候用 |
    |---|---|---|
    | `api` | 直接 HTTP POST 到模型 | 生产 |
    | `file` | 把请求写进 `.work/llm_queue/`，等外部把答案填进 `.res.txt` | **没密钥时测试整条管线** |

    `file` 后端不是玩具：它让"组装请求 → 等结果 → 落盘 → 跑门禁 → 不过就打回重做"
    这整条环在**没有密钥**的情况下也能端到端跑通。
    """
    cfg = load_config()
    if (cfg.get("backend") or "api").lower() == "file":
        return _chat_via_file(messages, cfg, timeout)
    return _chat_via_api(messages, cfg, temperature, max_tokens, timeout, retries)


def _chat_via_file(messages: list[dict], cfg: dict, timeout=None) -> str:
    import uuid
    QUEUE.mkdir(parents=True, exist_ok=True)
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    req = QUEUE / f"{rid}.req.json"
    res = QUEUE / f"{rid}.res.txt"
    req.write_text(json.dumps({
        "_how": "把答复写进同名的 .res.txt（纯文本，或 ```json 包一段 JSON）",
        "id": rid, "backend": "file",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "messages": messages,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📥 [file 后端] 请求已入队：{req.relative_to(ROOT)}")
    print(f"   填答：python tools/llm.py fulfill {rid} <答复文件>")
    wait = timeout or cfg.get("timeout_s") or 600
    deadline = time.time() + wait
    while time.time() < deadline:
        if res.exists():
            txt = res.read_text(encoding="utf-8-sig").strip()
            if txt:
                return txt
        time.sleep(1)
    raise LLMError(f"file 后端：等了 {wait}s 没人填答。请求在 {req.relative_to(ROOT)}")


def _chat_via_api(messages: list[dict], cfg: dict, temperature, max_tokens,
                  timeout, retries: int) -> str:
    key = api_key()
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "max_tokens": cfg["max_tokens"] if max_tokens is None else max_tokens,
        "stream": False,
    }
    last = None
    for i in range(retries + 1):
        try:
            res = _post(url, payload, key, cfg["timeout_s"] if timeout is None else timeout)
            ch = (res.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            txt = msg.get("content") or ""
            if not txt and msg.get("reasoning_content"):
                txt = msg["reasoning_content"]        # 推理模型兜底
            if not txt:
                raise LLMError(f"返回里没有正文：{json.dumps(res, ensure_ascii=False)[:400]}")
            return txt
        except LLMError as e:
            last = e
            if i < retries and ("连不上" in str(e) or "HTTP 5" in str(e) or "HTTP 429" in str(e)):
                time.sleep(2 + 3 * i)
                continue
            raise
    raise last  # pragma: no cover


def list_models(cfg: dict) -> list[str]:
    """拉 `/models` 列表。**不猜模型 id** —— 让端点自己说有哪些。"""
    key = _key_or_public()
    url = cfg["base_url"].rstrip("/") + "/models"
    req = urllib.request.Request(url, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} from {url}\n{e.read().decode('utf-8','replace')[:400]}") from None
    except urllib.error.URLError as e:
        raise LLMError(f"连不上 {url}：{e.reason}") from None
    return sorted(m.get("id", "?") for m in (data.get("data") or data.get("models") or []))


def _key_or_public() -> str:
    """`/models` 这类元数据查询允许用 OpenCode Zen 的匿名哨兵 `public`。"""
    try:
        return api_key()
    except LLMError:
        return "public"


def chat_json(messages: list[dict], **kw) -> dict:
    """要一段 JSON 回来。**模型爱在 JSON 外面裹 ``` 和说明文字**，这里把它剥掉。"""
    txt = chat(messages, **kw)
    return extract_json(txt)


def extract_json(txt: str) -> dict:
    t = txt.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise LLMError(f"回复里找不到 JSON 对象：\n{txt[:400]}")
    try:
        return json.loads(t[i:j + 1])
    except ValueError as exc:
        raise LLMError(f"JSON 解析失败：{exc}\n{t[i:i+400]}") from None


def cmd_pending() -> int:
    """列出 file 后端里还没人填答的请求。"""
    if not QUEUE.exists():
        print("（队列是空的）")
        return 0
    rows = []
    for f in sorted(QUEUE.glob("*.req.json")):
        rid = f.name[:-len(".req.json")]
        done = (QUEUE / f"{rid}.res.txt").exists()
        rows.append((rid, done, f))
    if not rows:
        print("（队列是空的）")
        return 0
    for rid, done, f in rows:
        print(f"{'✅' if done else '⏳'} {rid}  {f.stat().st_size} B"
              f"{'（已填答）' if done else '  ← 等填答'}")
    n = sum(1 for _, d, _ in rows if not d)
    print(f"\n共 {len(rows)} 条，{n} 条待填")
    return 0


def cmd_fulfill(rid: str, src: str) -> int:
    """把答复写进队列（`.res.txt`）。"""
    p = Path(src)
    if not p.is_absolute():
        p = ROOT / src
    if not p.exists():
        raise SystemExit(f"❌ 答复文件不存在：{p}")
    QUEUE.mkdir(parents=True, exist_ok=True)
    out = QUEUE / f"{rid}.res.txt"
    out.write_text(p.read_text(encoding="utf-8-sig"), encoding="utf-8")
    print(f"✅ 已填答 {out.relative_to(ROOT)}（{out.stat().st_size} B）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="模型通道（直连 HTTP API / file 队列）")
    ap.add_argument("cmd", choices=["ping", "ask", "config", "models",
                                    "pending", "fulfill"])
    ap.add_argument("text", nargs="?")
    ap.add_argument("src", nargs="?", help="fulfill 用：答复文件")
    a = ap.parse_args()

    if a.cmd == "config":
        cfg = load_config()
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        try:
            k = api_key()
            print(f"密钥：找到（{len(k)} 字符，来源 "
                  f"{'llm_key.txt' if KEY_FILE.exists() else '环境变量'}）—— **不回显**")
        except LLMError as e:
            print(f"密钥：❌ {e}")
        return 0

    if a.cmd == "models":
        try:
            cfg = load_config()
            ms = list_models(cfg)
            print(f"{cfg['base_url']} 上可用的模型（{len(ms)} 个）：")
            for m in ms:
                mark = " ← 当前配置" if m == cfg["model"] else ""
                print(f"  {m}{mark}")
            return 0
        except LLMError as e:
            print(f"❌ {e}")
            return 1

    if a.cmd == "pending":
        return cmd_pending()

    if a.cmd == "fulfill":
        if not a.text or not a.src:
            ap.error("fulfill 需要：<请求 id> <答复文件>")
        return cmd_fulfill(a.text, a.src)

    if a.cmd == "ping":
        try:
            t0 = time.time()
            out = chat([{"role": "user", "content": "只回复两个字：通了"}], max_tokens=20)
            print(f"✅ 通道正常（{time.time()-t0:.1f}s）：{out.strip()}")
            return 0
        except LLMError as e:
            print(f"❌ {e}")
            return 1

    if a.cmd == "ask":
        if not a.text:
            ap.error("ask 需要一句话")
        try:
            print(chat([{"role": "user", "content": a.text}]))
            return 0
        except LLMError as e:
            print(f"❌ {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
