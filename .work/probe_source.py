"""通用下载源探测器（按 agent.md 第四节：**下载前必须先探测源**）。

规矩（2026-09-19 用户明确要求）：
  * 任何 >50 MB 的下载，动手前先探测；
  * **样本要 ≥16 MB**——1 MB Range 会被握手/重定向开销带偏（曾报 1.9 MB/s，实际 17 MB/s）；
  * 顺序：列源 → HEAD → 大样本 Range 实测 → 算盘（留 10%）→ 选最快 → 下完校验。

用法（在云端跑）：
    python .work/run.py rpy .work/probe_source.py <规格名>
    python .work/run.py rpy .work/probe_source.py --list
    # 临时探一个没登记的目标：
    python .work/run.py rpy .work/probe_source.py --name X --expect 12345 --url URL1 --url URL2

新增目标：往下面 SPECS 里加一条即可。
"""
import argparse
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

TARGET = "/root/autodl-tmp"
LORAS = "/root/autodl-tmp/ComfyUI/models/loras"
DIFFUSION = "/root/autodl-tmp/ComfyUI/models/diffusion_models"

SAMPLE = 16 * 1024 * 1024          # 16 MB，足够摊掉握手开销

SPECS = {
    "ma-2511": {
        "desc": "Qwen-Image-Edit-2511 Multiple-Angles LoRA（fal）",
        "dest": LORAS,
        "expect": 295140688,       # 已用 HEAD 核实过
        "urls": [
            ("hf-api.gitee.com ★", "https://hf-api.gitee.com/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA"
                                   "/resolve/main/qwen-image-edit-2511-multiple-angles-lora.safetensors"),
            ("hf-mirror fal", "https://hf-mirror.com/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA"
                              "/resolve/main/qwen-image-edit-2511-multiple-angles-lora.safetensors"),
            ("hf-mirror AdversaLLC", "https://hf-mirror.com/AdversaLLC/Qwen-Image-Edit-2511-Multiple-Angles-LoRA"
                                     "/resolve/main/qwen-image-edit-2511-multiple-angles-lora.safetensors"),
            ("hf official fal", "https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA"
                                "/resolve/main/qwen-image-edit-2511-multiple-angles-lora.safetensors"),
        ],
        # 2026-09-19 实测（281 MB）：单连接 hf-mirror 196 KB/s、gitee 580 KB/s；
        # **16 路并行 gitee 达 4.16 MB/s，68 秒下完**。→ 单连接测速会严重低估，见 dl_chunked.py。
        "note": "实测最快是 gitee + 16 路并行；本脚本只测单连接，选源后请用 dl_chunked.py 并行下。",
    },
}


def head(url, timeout=25):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, int(r.headers.get("Content-Length") or 0), r.geturl()


def range_speed(url, nbytes=SAMPLE, timeout=90):
    """实测吞吐：读满 nbytes 或读到流结束。返回 (字节数, MB/s)。"""
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8",
                                              "Range": "bytes=0-%d" % (nbytes - 1)})
    t0 = time.time()
    got = 0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while got < nbytes:
            chunk = r.read(262144)
            if not chunk:
                break
            got += len(chunk)
    dt = max(1e-6, time.time() - t0)
    return got, got / dt / 1048576.0


def probe(name, spec):
    sys.stdout.reconfigure(encoding="utf-8")
    total, used, free = shutil.disk_usage(TARGET)
    print("=" * 78)
    print("目标：%s  （%s）" % (name, spec.get("desc", "")))
    print("落盘目录：%s（存在=%s）" % (spec["dest"], os.path.isdir(spec["dest"])))
    print("磁盘 %s：可用 **%.2f GB**" % (TARGET, free / 2**30))
    if spec.get("expect"):
        need = spec["expect"] * 1.10
        print("预期大小 %.0f MB；含 10%% 余量需要 %.2f GB → %s"
              % (spec["expect"] / 2**20, need / 2**30,
                 "装得下 ✅" if need < free else "★装不下 ❌"))
    print()
    print("%-24s %-6s %-12s %-16s %s" % ("源", "HTTP", "大小", "实测(16MB样本)", "判断"))
    best = None
    for label, url in spec["urls"]:
        try:
            st, size, _final = head(url)
        except urllib.error.HTTPError as e:
            print("%-24s %-6s %s" % (label, e.code, "HEAD 失败，跳过")); continue
        except Exception as e:                                       # noqa: BLE001
            print("%-24s %-6s %s" % (label, "失败", str(e)[:50])); continue
        try:
            got, mbs = range_speed(url)
        except Exception as e:                                       # noqa: BLE001
            print("%-24s %-6s %-12s %s" % (label, st, "%.0f MB" % (size / 2**20),
                                           "Range 失败：" + str(e)[:40])); continue
        note = ""
        if spec.get("expect") and size and size != spec["expect"]:
            note = "⚠️ 大小与预期不符"
        if got < SAMPLE:
            note = (note + " " if note else "") + "⚠️ 只读到 %.0f MB（可能不支持 Range）" % (got / 2**20)
        print("%-24s %-6s %-12s %-16s %s" % (label, st, "%.0f MB" % (size / 2**20),
                                             "%.2f MB/s" % mbs, note or "OK"))
        if best is None or mbs > best[0]:
            best = (mbs, label, url, size)
    print()
    if best:
        eta = best[3] / (best[0] * 1048576) if best[0] > 0 else 0
        print("★ 推荐：%s —— %.2f MB/s，%.0f MB，预计 %.0f 秒" % (best[1], best[0], best[3] / 2**20, eta))
        print("  URL: %s" % best[2])
    else:
        print("★ 没有可用源——**什么都不要删**，先换源再试。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", nargs="?", help="规格名；--list 看全部")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--name")
    ap.add_argument("--expect", type=int, default=0)
    ap.add_argument("--dest", default=LORAS)
    ap.add_argument("--url", action="append", default=[])
    a = ap.parse_args()
    if a.list:
        for k, v in SPECS.items():
            print("%-14s %s" % (k, v.get("desc", "")))
        return 0
    if a.name and a.url:
        spec = {"desc": "ad-hoc", "dest": a.dest, "expect": a.expect,
                "urls": [("url%d" % (i + 1), u) for i, u in enumerate(a.url)]}
        return probe(a.name, spec)
    if a.spec in SPECS:
        return probe(a.spec, SPECS[a.spec])
    print("未知规格 %r；用 --list 看已登记的。" % a.spec)
    return 2


if __name__ == "__main__":
    sys.exit(main())
