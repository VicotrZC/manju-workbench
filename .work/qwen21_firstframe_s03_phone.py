"""Create the phone-evidence camera-cut frame using Qwen-Image 2.1 assets."""
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
    ("8", "Q21_ASSET_PHONE.png"),
]
graph = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
}
for node_id, filename in refs:
    graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}
graph["9"] = {"class_type": "TextEncodeQwenImage21", "inputs": {
    "clip": ["2", 0],
    "prompt": (
        "A polished premium Chinese 3D donghua frame, clearly animated not live-action: gently stylized adult faces, "
        "expressive eyes, softened sculpted forms, clean animation shading and painted texture accents; keep the same style as the approved Qwen 2.1 market keyframe. "
        "Use <image1> for the exact same modern pork stall, red hanging lamps, hanging pork and counter. "
        "Use <image2> and <image3> for the exact young male customer in black T-shirt, dark trousers, white sneakers and the same face. "
        "Use <image4> for the same middle-aged butcher in a navy shirt and brown apron. Use <image5> as the exact black phone prop and as a guide to its screen content only. "
        "Create a 16:9 over-the-counter medium close two-shot at the same market, an intentional cut closer from the previous wide counter view. "
        "Keep the customer on frame left and butcher on frame right, facing each other across the same counter. The butcher holds one black smartphone in the foreground between them, "
        "tilted toward both the customer and camera so the portrait screen is clearly visible and large enough to read visually. "
        "On the screen show a short video still of a small farm truck carrying several healthy, lively pink piglets toward a clean rural processing-facility gate; "
        "cute but not childish, no distress, no blood. The young man's eyes are fixed on the phone, expression skeptical but attentive; butcher is earnest and matter-of-fact. "
        "Keep the same red lamps and a few hanging cuts visible in the softly blurred market background. Modern clothes and modern market only. "
        "No extra people, no second phone, no text, no readable signs, no captions, no split screen, no fantasy or ancient elements."
    ),
    "negative_prompt": "photograph, live action, photorealistic skin pores, flat 2D anime, chibi, ancient clothes, extra people, duplicated phone, text, subtitles",
    "resolution": 1024,
    "images": [{"image": [node_id, 0]} for node_id, _ in refs],
    "vae": ["3", 0],
}}
graph["10"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}}
graph["11"] = {"class_type": "KSampler", "inputs": {
    "model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["10", 0],
    "seed": 920305, "steps": 35, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
graph["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}}
graph["13"] = {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "Q21_KEYFRAME_S03_phone_v1"}}


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
        images = item.get("outputs", {}).get("13", {}).get("images", [])
        if not images:
            raise SystemExit("Qwen returned no image")
        output = images[0]
        query = urllib.parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": output.get("type", "output")})
        with urllib.request.urlopen(BASE + "/view?" + query, timeout=60) as response:
            data = response.read()
        destination = OUT / "Q21_KEYFRAME_S03_phone_v1.png"
        destination.write_bytes(data)
        print("saved", destination, len(data), flush=True)
        break
    time.sleep(2)
else:
    raise SystemExit("timed out")
