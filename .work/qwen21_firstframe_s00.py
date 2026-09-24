"""Generate the first outbound-ride frame with Qwen-Image 2.1 multi-reference conditioning."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8189"
graph = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
    "4": {"class_type": "LoadImage", "inputs": {"image": "Q21_ASSET_STREET.png"}},
    "5": {"class_type": "LoadImage", "inputs": {"image": "Q21_ASSET_CHR01_BODY.png"}},
    "6": {"class_type": "LoadImage", "inputs": {"image": "Q21_ASSET_CHR01_FACE.png"}},
    "7": {"class_type": "LoadImage", "inputs": {"image": "Q21_ASSET_EBIKE.png"}},
    "8": {"class_type": "TextEncodeQwenImage21", "inputs": {
        "clip": ["2", 0],
        "prompt": (
            "Create an original cinematic frame for a contemporary Chinese 3D animated drama. "
            "Use <image1> as the fixed modern residential street environment: preserve its tree-lined "
            "two-lane road, cool-white lamps, iron fences, sidewalk and scooter shelter, under predawn blue light. "
            "Use <image2> for the exact identity, hairstyle, black T-shirt, dark trousers and white shoes of the "
            "young male protagonist; use <image3> for his exact face and small scar above the outer end of his left eyebrow. "
            "Use <image4> for the exact blue-gray step-through electric scooter, one seat and rear rack. "
            "Wide 16:9 landscape frame, rear three-quarter camera at natural street height. The young man rides "
            "alone away from camera toward the road's vanishing point, centered low in the frame, both hands on the "
            "handlebars, both wheels touching the road, believable seated posture. The scooter points away from the "
            "camera along the street. Rear seat and rack are empty. Quiet 4 a.m. blue hour, wet-road reflections "
            "remain subtle. Mature stylized Chinese 3D animation rendering, expressive but restrained, refined "
            "sculpted forms, detailed rendered fabric, soft volumetric light and cinematic color grading. "
            "Keep it contemporary: no ancient clothing, no fantasy or magic. No extra people, no traffic, no text, "
            "no signage, no collage, no split panels."
        ),
        "negative_prompt": "", "resolution": 1024,
        "images": [
            {"image": ["4", 0]}, {"image": ["5", 0]},
            {"image": ["6", 0]}, {"image": ["7", 0]},
        ], "vae": ["3", 0]}},
    "9": {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}},
    "10": {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "positive": ["8", 0], "negative": ["8", 1],
        "latent_image": ["9", 0], "seed": 920301, "steps": 35, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
    "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
    "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": "Q21_KEYFRAME_S00_outbound_v1"}},
}

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
