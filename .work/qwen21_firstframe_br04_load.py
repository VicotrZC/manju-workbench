"""Create the post-purchase scooter-loading frame with Qwen-Image 2.1."""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8188"
OUT = Path(__file__).resolve().parents[1] / "projects" / "美食：全市巡摆，馋哭食客" / "outputs" / "QWEN21_STYLE_V1"
OUT.mkdir(parents=True, exist_ok=True)
refs = [
    ("4", "Q21_H3_S05_END.png"),
    ("5", "Q21_ASSET_MARKET_ENTRY.png"),
    ("6", "Q21_ASSET_STALL.png"),
    ("7", "Q21_ASSET_CHR01_BODY.png"),
    ("8", "Q21_ASSET_CHR01_FACE.png"),
    ("9", "Q21_ASSET_EBIKE.png"),
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
        "A polished premium Chinese 3D donghua frame, clearly animated rather than live-action: gently stylized adult faces, "
        "expressive eyes, softened sculpted forms, clean animation shading and painted texture accents; match the approved Qwen 2.1 market shots. "
        "Use <image1> only to preserve the exact young man's identity, outfit and the same wrapped pork parcel that he has just received; "
        "do not preserve its counter composition. Use <image2> and <image3> for the same modern covered wet-market entrance, aisle and left-side pork stall with red lamps and hanging meat. "
        "Use <image4> and <image5> for the exact young male protagonist in black T-shirt, dark trousers and white sneakers. Use <image6> for the exact blue-gray step-through scooter and rear rack. "
        "Create a wide 16:9 side/rear three-quarter view inside the same market aisle, a planned cut from the counter to the scooter. "
        "Show only one protagonist and one scooter. The man stands beside the scooter holding exactly ONE wrapped parcel in both hands at waist height, before loading it. "
        "The scooter's metal rear rack is completely bare and empty, clearly visible behind him. There is exactly ONE parcel total in the entire image: "
        "the parcel held in his hands. There is no parcel, bag or meat on the scooter, rack, ground or counter. "
        "Make this single parcel visibly substantial for a fifty-jin (about 25 kg) purchase, broad and heavy enough to fill most of the rear rack when loaded, "
        "but still one securely tied white butcher parcel; preserve the wrapper and small clear panel from <image1>. "
        "Keep the scooter side profile and rack unobstructed. The pork stall with red lamps and hanging cuts remains recognizable behind him on the left; cool dawn light enters from the market opening. "
        "Modern casual clothing and present-day market only. No extra customer, no duplicate parcels, no second scooter, no text, no signs, no captions, no fantasy or ancient elements."
    ),
    "negative_prompt": "photograph, live action, photorealistic pores, flat 2D anime, chibi, ancient clothes, extra people, extra parcels, second bag, package on scooter, parcel on rear rack, duplicate vehicle, text, subtitles",
    "resolution": 1024,
    "images": [{"image": [node_id, 0]} for node_id, _ in refs],
    "vae": ["3", 0],
}}
graph["11"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}}
graph["12"] = {"class_type": "KSampler", "inputs": {
    "model": ["1", 0], "positive": ["10", 0], "negative": ["10", 1], "latent_image": ["11", 0],
    "seed": 920308, "steps": 35, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
graph["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
graph["14"] = {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": "Q21_KEYFRAME_BR04_load_v2"}}


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
        destination = OUT / "Q21_KEYFRAME_BR04_load_v2.png"
        destination.write_bytes(data)
        print("saved", destination, len(data), flush=True)
        break
    time.sleep(2)
else:
    raise SystemExit("timed out")
