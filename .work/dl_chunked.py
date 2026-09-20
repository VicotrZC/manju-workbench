"""分块并行下载（按 agent.md 第四节：下载前先探测源，再选最快源）。

为什么需要它：本机到各镜像的**单连接**速度都被限得很死——
  * hf-mirror.com        单连接 196 KB/s ｜ 8 路并行 950 KB/s
  * hf-api.gitee.com     单连接 580 KB/s ｜ 8 路并行 **2457 KB/s**  ← 本次最快
  * huggingface.co       不可达（http=000）
  * modelscope.cn        2.8 MB/s（但没有这个 LoRA 的副本）
281 MB 单连接要 24 分钟；8 路并行约 2 分钟。所以走分块并行。

用法（云端跑）：
    python .work/run.py rpy .work/dl_chunked.py <URL> <输出路径> <总字节数> [分块数]
"""
import concurrent.futures as cf
import json
import os
import struct
import subprocess
import sys
import time

UA = "curl/8"


def head_size(url):
    out = subprocess.run(["curl", "-sIL", "--max-time", "25", "-A", UA, url],
                         capture_output=True, text=True).stdout
    size = 0
    for line in out.splitlines():
        if line.lower().startswith("content-length:"):
            size = int(line.split(":", 1)[1].strip())
    return size


def fetch(url, start, end, path, timeout=600):
    tmp = path + ".part"
    cmd = ["curl", "-sL", "--fail", "--connect-timeout", "10", "--max-time", str(timeout),
           "-A", UA, "-r", "%d-%d" % (start, end), "-o", tmp, url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("chunk %d-%d curl 退出码 %d: %s" % (start, end, r.returncode, r.stderr[:200]))
    got = os.path.getsize(tmp)
    want = end - start + 1
    if got != want:
        raise RuntimeError("chunk %d-%d 大小不对：得到 %d，应为 %d" % (start, end, got, want))
    os.replace(tmp, path)
    return got


def verify_safetensors(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n <= 0 or n > 200 * 1024 * 1024:
            raise RuntimeError("safetensors 头长度异常：%d" % n)
        hdr = json.loads(f.read(n))
    return len(hdr)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    url, out, total, nchunks = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 16
    real = head_size(url)
    print("URL: %s" % url)
    print("HEAD 报的大小 %d；调用方给的总大小 %d → %s"
          % (real, total, "一致 ✅" if real == total else "★不一致，以 HEAD 为准"))
    if real and real != total:
        total = real
    per = total // nchunks
    ranges = []
    for i in range(nchunks):
        s = i * per
        e = total - 1 if i == nchunks - 1 else (s + per - 1)
        ranges.append((s, e, "/tmp/dlchunk_%03d" % i))

    t0 = time.time()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=nchunks) as ex:
        futs = {ex.submit(fetch, url, s, e, p): (s, e) for s, e, p in ranges}
        for fu in cf.as_completed(futs):
            s, e = futs[fu]
            try:
                done += fu.result()
            except Exception as exc:                              # noqa: BLE001
                print("❌ 分块 %d-%d 失败：%s" % (s, e, exc))
                return 1
            print("  ✔ %d-%d  (累计 %.0f/%.0f MB)" % (s, e, done / 2**20, total / 2**20), flush=True)
    dt = max(1e-6, time.time() - t0)

    tmp_out = out + ".assembling"
    with open(tmp_out, "wb") as w:
        for _s, _e, p in ranges:
            with open(p, "rb") as r:
                while True:
                    b = r.read(8 << 20)
                    if not b:
                        break
                    w.write(b)
    got = os.path.getsize(tmp_out)
    if got != total:
        print("❌ 拼装后大小 %d != %d" % (got, total))
        return 1
    os.replace(tmp_out, out)
    for _s, _e, p in ranges:
        os.remove(p)

    print("\n✅ 下载完成 %.0f MB，用时 %.0f 秒（**%.2f MB/s**）"
          % (total / 2**20, dt, total / dt / 2**20))
    print("落盘：%s" % out)
    try:
        print("safetensors 头部校验 ✅ 张量数 %d" % verify_safetensors(out))
    except Exception as exc:                                      # noqa: BLE001
        print("❌ safetensors 校验失败：%s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
