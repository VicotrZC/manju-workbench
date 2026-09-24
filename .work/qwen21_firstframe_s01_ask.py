"""Generate the market-counter ask-price keyframe from approved Qwen 2.1 refs."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8188"
OUT = Path(__file__).resolve().parents[1] / "projects" / "美食：全市巡摆，馋哭食客" / "outputs" / "QWEN21_STYLE_V1"
OUT.mkdir(parents=True, exist_ok=True)

refs = [
    ("4", "Q21_ASSET_STALL.png"),
    ("5", "Q21_ASSET_CHR01_BODY.png"),
    ("6", "Q21_ASSET_CHR01_FACE.png"),
    ("7", "Q21_ASSET_CHR02_VENDOR.png"),
    ("8", "Q21_ASSET_EBIKE.png"),
    ("9", "Q21_ASSET_PORK.png"),
]
graph = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
}
for node_id, filename in refs:
    graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}

graph["10"] = {"class_type": "TextEncodeQwenImage21", "inputs": {
    "clip": ["2", 0],
    "prompt": (
        "Create a polished premium Chinese 3D donghua frame, clearly designed and animated rather than a live-action still: "
        "slightly stylized sculpted faces and facial planes, subtly enlarged expressive eyes, clean softened forms, "
        "smooth animation shading with painted texture accents, carefully art-directed fabrics and cinematic color. "
        "Keep natural adult human proportions; no chibi, no photoreal skin, no visible pores. "
        "Use <image1> for the exact compact pork-stall layout, hanging cuts, five warm red pendant lamps, counter, metal trays and dark doorway. "
        "Use <image2> for the exact young male lead's build and black T-shirt, dark trousers and white shoes; use <image3> for his exact animated face and hairstyle. "
        "Use <image4> for the exact middle-aged male butcher's face, navy work shirt and brown apron. "
        "Use <image5> for the exact blue-gray step-through scooter. Use <image6> for fresh red-and-white pork on the counter. "
        "Make a stable medium-wide over-the-shoulder two-shot from the aisle, same left-to-right screen direction as <image1>. "
        "The young man has dismounted and is standing beside the parked scooter at the customer side of the same counter, facing the butcher. "
        "The butcher faces him from behind the counter. Both are calm, making eye contact as the customer begins to ask the price. "
        "Keep hanging pork clearly visible above and behind them; the scooter remains parked a few steps behind the customer, rear rack empty. "
        "Preserve the recognizable stall structure and red lamps; no scene change, no duplicate people, no extra customer, no new vehicle, "
        "no text, no signs or letters, no captions, no collage, no split panels. Contemporary clothes and present-day wet market only; no ancient or fantasy elements."
    ),
    "negative_prompt": "photograph, live action, photorealistic skin pores, flat 2D anime, chibi, ancient costume, extra people, duplicated faces, gibberish lettering, captions",
    "resolution": 1024,
    "images": [{"image": [node_id, 0]} for node_id, _ in refs],
    "vae": ["3", 0],
}}
graph["11"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}}
graph["12"] = {"class_type": "KSampler", "inputs": {
    "model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1], "latent_image": ["11", 0],
    "seed": 920304, "steps": 35, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
graph["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
graph["14"] = {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": "Q21_KEYFRAME_S01_ask_price_v2"}}


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


request = urllib.request.Request(BASE + "/prompt", data=json.dumps({"prompt": graph}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=30) as response:
    prompt_id = json.load(response)["prompt_id"]
print("submitted", prompt_id, flush=True)
for _ in range(1200):
    history = get_json("/history/" + prompt_id)
    if prompt_id in history:
        item = history[prompt_id]
        status = item.get("status", {}).get("status_str")
        print("status", status, flush=True)
        if status != "success":
            raise SystemExit(1)
        images = item.get("outputs", {}).get("14", {}).get("images", [])
        if not images:
            raise SystemExit("Qwen returned no image")
        output = images[0]
        query = urllib.parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": output.get("type", "output")})
        with urllib.request.urlopen(BASE + "/view?" + query, timeout=60) as response:
            data = response.read()
        destination = OUT / "Q21_KEYFRAME_S01_ask_price_v2.png"
        destination.write_bytes(data)
        print("saved", destination, len(data), flush=True)
        break
    time.sleep(2)
else:
    raise SystemExit("timed out")
