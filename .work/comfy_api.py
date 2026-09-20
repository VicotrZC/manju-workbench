"""ComfyUI API client: convert a CANVAS workflow into API format and run it.

Why this exists: the canvas format (nodes/links/widgets_values) is NOT what
POST /prompt accepts. The handover explicitly warns these two formats are not
interchangeable, so the canvas files stay the source of truth for the user while
this module derives the API payload from them.

The widget-name table below was verified against the live backend's /object_info
(dumped to .work/object_info.json), including frontend-only values (marked None)
that must NOT be sent, such as KSampler's control_after_generate and LoadImage's
upload button.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8188"          # local end of the SSH tunnel
ROOT = Path(r"E:\Learn\minimax-h3-cloud")

# widget_values layout per class, in the order the ComfyUI frontend stores them.
# None = frontend-only value, skipped when building the API payload.
WIDGET_LAYOUT = {
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "ModelSamplingAuraFlow": ["shift"],
    "CFGNorm": ["strength", None],   # 画布上有 2 格，后端只收 strength（第二格是前端专用）
    "LoadImage": ["image", None],
    "FluxKontextImageScale": [],
    "FluxKontextMultiReferenceLatentMethod": ["reference_latents_method"],
    "VAEEncode": [],
    "TextEncodeQwenImageEditPlus": ["prompt"],
    "KSampler": ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "VAEDecode": [],
    "SaveImage": ["filename_prefix"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "CLIPTextEncode": ["text"],
    # ---- MiniMax H3 video chain (verified against the live /object_info) ----
    "MiniMaxH3ImageToVideo": ["prompt", "width", "height", "length"],
    "MiniMaxH3ReferenceToVideo": ["prompt", "width", "height", "length", "ref_image_size"],
    "RandomNoise": ["noise_seed", None],
    "BasicGuider": [],
    "KSamplerSelect": ["sampler_name"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "SamplerCustomAdvanced": [],
    "VAEDecodeAudio": [],
    "CreateVideo": ["fps"],
    "SaveVideo": ["filename_prefix", "format", "codec"],
    "ImageScaleToTotalPixels": ["upscale_method", "megapixels", "resolution_steps"],
    # ---- native video nodes (verified via /object_info) ----
    "LoadVideo": ["file"],
    "GetVideoComponents": [],
    "VideoTemporalCrop": ["start_frame", "length"],
    "VideoFrameSample": ["num_frames", "strategy", "seed"],
    "Video Slice": ["start_time", "duration", "strict_duration"],
}


FRONTEND_ONLY = {"MarkdownNote", "Note"}   # exist on canvas, never sent to the API


class ValidationError(RuntimeError):
    pass


def to_api_prompt(wf: dict) -> dict:
    """Canvas workflow -> API prompt. Fails loudly rather than guessing."""
    nodes = wf["nodes"]
    links = {l[0]: l for l in wf.get("links", [])}
    by_id = {n["id"]: n for n in nodes}

    for n in nodes:
        for inp in n.get("inputs") or []:
            if "widget" in inp:
                raise ValidationError(
                    "node %s (%s) has a widget converted to an input; the converter "
                    "does not handle that case" % (n["id"], n.get("type")))

    prompt = {}
    for n in nodes:
        if n.get("mode", 0) != 0:           # bypassed/muted -> excluded
            continue
        cls = n.get("type")
        if cls in FRONTEND_ONLY:
            continue
        if cls == "Reroute":
            raise ValidationError("Reroute nodes need link resolution; not supported")
        if cls not in WIDGET_LAYOUT:
            raise ValidationError("unknown node class: %s" % cls)
        layout = WIDGET_LAYOUT[cls]
        wv = n.get("widgets_values") or []
        if len(wv) != len(layout):
            raise ValidationError(
                "node %s (%s): %d widget values but layout expects %d %s"
                % (n["id"], cls, len(wv), len(layout), layout))

        inputs = {}
        for name, val in zip(layout, wv):
            if name is not None:
                inputs[name] = val
        for inp in n.get("inputs") or []:
            lid = inp.get("link")
            if lid is None:
                continue
            l = links.get(lid)
            if l is None:
                raise ValidationError("node %s input %s references missing link %s"
                                      % (n["id"], inp.get("name"), lid))
            inputs[inp["name"]] = [str(l[1]), l[2]]
        prompt[str(n["id"])] = {"class_type": cls, "inputs": inputs}

    # a node we skipped must not still be feeding an included node
    for n in nodes:
        if n.get("mode", 0) == 0:
            continue
        for out in n.get("outputs") or []:
            if out.get("links"):
                raise ValidationError(
                    "bypassed node %s still feeds %s; rewire before converting"
                    % (n["id"], out["links"]))
    return prompt


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise ValidationError("HTTP %s from %s: %s" % (e.code, path, body[:900])) from None


def _get(path: str, timeout: int = 60):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def submit(api_prompt: dict) -> str:
    res = _post("/prompt", {"prompt": api_prompt, "client_id": "dsh-automation"})
    errs = res.get("node_errors") or {}
    if errs:
        raise ValidationError("node_errors: " + json.dumps(errs, ensure_ascii=False)[:1200])
    return res["prompt_id"]


def wait(prompt_id: str, timeout_s: int = 900, poll_s: float = 4.0) -> dict:
    """Block until the run finishes; return its history entry."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hist = _get("/history/%s" % prompt_id, timeout=30)
        entry = hist.get(prompt_id)
        if entry:
            status = entry.get("status", {})
            if status.get("completed") or status.get("status_str") in ("success", "error"):
                return entry
        time.sleep(poll_s)
    raise TimeoutError("prompt %s did not finish within %ss" % (prompt_id, timeout_s))


def output_files(entry: dict) -> list:
    files = []
    for out in (entry.get("outputs") or {}).values():
        for img in out.get("images", []):
            files.append(img)
    return files


def download(img: dict, dest_dir: Path, attempts: int = 4) -> Path:
    """下载一张产物。带重试：实测隧道偶发 WinError 10054（连接被重置），
    一次抖动不该让整批 8 件的任务在最后一步全废。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    q = "filename=%s&subfolder=%s&type=%s" % (
        urllib.parse.quote(img["filename"]),
        urllib.parse.quote(img.get("subfolder", "")),
        urllib.parse.quote(img.get("type", "output")))
    dest = dest_dir / img["filename"]
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(BASE + "/view?" + q, timeout=180) as r:
                data = r.read()
            if not data:
                raise IOError("empty body")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return dest
        except Exception as e:                     # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(2 + 3 * i)
    raise IOError("download failed after %d attempts: %s" % (attempts, last))


def run_canvas_workflow(path: Path, dest_dir: Path, timeout_s: int = 900) -> tuple:
    """Convert + submit + wait + download. Returns (prompt_id, [local paths])."""
    wf = json.loads(Path(path).read_text(encoding="utf-8"))
    api = to_api_prompt(wf)
    pid = submit(api)
    entry = wait(pid, timeout_s=timeout_s)
    status = entry.get("status", {})
    if status.get("status_str") == "error":
        raise ValidationError("run failed: " + json.dumps(status, ensure_ascii=False)[:900])
    saved = [download(i, dest_dir) for i in output_files(entry)]
    return pid, saved
