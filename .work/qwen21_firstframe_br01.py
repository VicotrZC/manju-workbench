"""Create the actual street-to-market entrance keyframe with Qwen-Image 2.1."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8189"
graph = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
}
references = [
    ("4", "Q21_ASSET_MARKET_ENTRY.png"),
    ("5", "Q21_ASSET_CHR01_BODY.png"),
    ("6", "Q21_ASSET_CHR01_FACE.png"),
    ("7", "Q21_ASSET_EBIKE.png"),
    ("8", "Q21_ASSET_CHR02_VENDOR.png"),
]
for node_id, filename in references:
    graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": filename}}

graph["9"] = {"class_type": "TextEncodeQwenImage21", "inputs": {
    "clip": ["2", 0],
    "prompt": (
        "Make a wide 16:9 establishing frame in the same mature, polished Chinese 3D animated-series look. "
        "<image1> is the modern covered wet-market entrance and left-side pork-stall environment reference only. "
        "Ignore and replace all people, faces, scooters, text and signs in <image1>; preserve its roof, columns, "
        "central rideable aisle, street-to-market threshold and the pork stall on the LEFT just inside. "
        "<image2> defines the exact young male protagonist's full-body build, black T-shirt, dark trousers and "
        "white shoes. <image3> defines his face and eyebrow scar. <image4> defines the single blue-gray step-through "
        "electric scooter. <image5> defines the middle-aged pork seller in a navy work shirt and brown apron. "
        "At predawn, show exactly one young man on the scooter entering the market from the street, seen from behind "
        "in a wide rear three-quarter view. He is just crossing the threshold and riding toward the left-side pork "
        "stall, which is visible ahead with its red lights and hanging pork. The butcher may stand behind that stall. "
        "No other customers, no duplicate riders, no signs, no readable or gibberish letters, no captions. "
        "Cool blue outdoor dawn light meets warm market lamps. Natural proportions, richly rendered animation "
        "materials, cinematic depth, one coherent scene, not a collage."
    ),
    "negative_prompt": "", "resolution": 1024,
    "images": [{"image": [node_id, 0]} for node_id, _ in references], "vae": ["3", 0]}}
graph["10"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}}
graph["11"] = {"class_type": "KSampler", "inputs": {
    "model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["10", 0],
    "seed": 920302, "steps": 35, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
graph["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}}
graph["13"] = {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "Q21_KEYFRAME_BR01_market_entry_v1"}}


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


request = urllib.request.Request(BASE + "/prompt", data=json.dumps({"prompt": graph}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=30) as response:
    prompt_id = json.load(response)["prompt_id"]
print("submitted", prompt_id, flush=True)
for _ in range(1200):
    history = get("/history/" + prompt_id)
    if prompt_id in history:
        item = history[prompt_id]
        print("status", item.get("status", {}).get("status_str"), flush=True)
        print("outputs", json.dumps(item.get("outputs", {}))[:700], flush=True)
        if item.get("status", {}).get("status_str") != "success":
            raise SystemExit(1)
        break
    time.sleep(2)
else:
    raise SystemExit("timed out")
