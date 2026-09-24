"""Stylize this story's approved modern reference assets using Qwen-Image 2.1."""

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8189"

STYLE = (
    "Convert the image into a polished, mature Chinese 3D animated series frame. "
    "Use clearly computer-rendered animation rather than live-action photography: refined sculpted forms, "
    "natural believable proportions, subtly idealized faces, smooth but detailed materials, "
    "softly painted texture detail, cinematic global illumination, gentle volumetric light, "
    "controlled warm-and-cool color grading, elegant depth and carefully art-directed shadows. "
    "Grounded contemporary Chinese daily life. Keep the modern present-day setting and objects. "
    "Do not add fantasy, cultivation, ancient architecture, ancient clothing, magic, calligraphy or text. "
)

TASKS = [
    {
        "name": "CHR01_BODY",
        "file": "Q21_SRC_CHR01_body.png",
        "refs": ["Q21_SRC_CHR01_face.png"],
        "seed": 920241,
        "prompt": (
            "Edit <image1> while preserving the young man's exact identity, pose, full-body framing, "
            "short messy black hair, black T-shirt, charcoal trousers, white sneakers and old scar above "
            "the outer end of his left eyebrow. Use <image2> only as the close-up identity reference for his face. "
            "Create the same character in the animation rendering style, head to shoes, neutral stance, "
            "simple gray studio background. Keep the shirt plain and unbranded. "
        ),
    },
    {
        "name": "CHR01_FACE",
        "file": "Q21_SRC_CHR01_face.png",
        "refs": [],
        "seed": 920242,
        "prompt": (
            "Restyle this exact young Chinese man's face as an original character from a mature 3D animated series. "
            "Preserve his identity, face shape, dark eyes, short black hair, age and the small old scar above the "
            "outer end of his left eyebrow. Close three-quarter portrait, natural neutral expression, modern black "
            "shirt, softly lit gray background. Animated sculpted facial planes and expressive eyes, clean smooth "
            "skin with subtle painted texture, not photoreal. "
        ),
    },
    {
        "name": "CHR02_VENDOR",
        "file": "Q21_SRC_CHR02_vendor.png",
        "refs": [],
        "seed": 920243,
        "prompt": (
            "Restyle this exact middle-aged Chinese man, preserving his face, stocky build, short black hair, "
            "navy short-sleeve work shirt, dark brown waterproof butcher apron and calm kind expression. "
            "Full body front three-quarter view, same gray background, mature stylized 3D animation character render. "
            "Keep the apron clean enough for a food-market scene, with a few understated work marks. "
        ),
    },
    {
        "name": "EBIKE",
        "file": "Q21_SRC_EBIKE.png",
        "refs": [],
        "seed": 920244,
        "prompt": (
            "Restyle this exact blue-gray step-through electric scooter as a prop from a polished 3D animated series. "
            "Preserve the side profile, wheel size, frame geometry, single saddle, rear cargo rack, mirrors, headlight, "
            "fenders, color and proportions. Neutral gray studio background, clean stylized CGI materials with "
            "crisp details, no rider, no extra basket, no logos, no text. "
        ),
    },
    {
        "name": "STALL",
        "file": "Q21_SRC_STALL.png",
        "refs": [],
        "seed": 920245,
        "prompt": (
            "Restyle <image1> as a polished mature Chinese 3D animated series environment. Preserve this exact "
            "straight-on pork stall architecture and object placement: central dark wooden door; exactly five red "
            "pendant lamps in one row; the same hanging pork cuts across the rail; three red sausages on the right; "
            "white foam chest at lower left; blue crate and white bucket at lower right; white tiled wall and long "
            "counter. Keep the same camera, framing and geometry. Predawn warm stall lights with cool ambient fill. "
            "Rendered animation, detailed but gently painterly PBR surfaces, no people, no labels, no new props. "
        ),
    },
    {
        "name": "STREET",
        "file": "Q21_SRC_STREET.png",
        "refs": [],
        "seed": 920246,
        "prompt": (
            "Restyle <image1> as a cinematic 3D animated series environment, preserving the exact modern Chinese "
            "residential street layout, straight two-lane road and vanishing point, repeating cool-white street lamps "
            "on the left, mature trees and iron fences on both sides, and the metal scooter shelter on the right. "
            "Predawn blue night, no people, no vehicles in the road, same camera and composition. Clearly animated "
            "render with polished environmental materials, restrained painterly detail and soft volumetric light. "
        ),
    },
    {
        "name": "MARKET_ENTRY",
        "file": "Q21_SRC_MARKET_ENTRY.png",
        "refs": [],
        "seed": 920247,
        "prompt": (
            "Restyle <image1> as a cinematic 3D animated series environment, preserving the exact view from the "
            "modern street into the open covered wet-market entrance. Keep the entrance centered, the rideable aisle "
            "leading inside, and the pork stall on the left after entering. Preserve the same columns, roof, trees, "
            "street lamps, dawn-dark exterior and warm stall lights. No people or vehicles. Clearly animated render, "
            "contemporary Chinese market, gently painterly detailed surfaces, soft volumetric lighting. "
        ),
    },
    {
        "name": "PORK",
        "file": "Q21_SRC_PORK.png",
        "refs": [],
        "seed": 920248,
        "prompt": (
            "Restyle this exact single slab of fresh black pork, preserving the dark rind edge and its marbled "
            "lean-and-fat pattern. Food-prop close-up for a mature 3D animated series, restrained painterly CGI, "
            "clean steel tray, neutral background, no text, no extra meat, appetizing but realistic anatomy of the cut. "
        ),
    },
    {
        "name": "PHONE",
        "file": "Q21_SRC_PHONE.png",
        "refs": [],
        "seed": 920249,
        "prompt": (
            "Restyle this exact black smartphone as a prop from a polished 3D animated series. Preserve the portrait "
            "screen and the image on it: a small farm truck carrying lively pigs entering a clean farm gate. Keep the "
            "screen readable as a tiny video but do not add interface text or captions. Neutral gray studio background, "
            "same angle, stylized CGI material, no hands, no blood, no distressing content. "
        ),
    },
]


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


def run(task):
    image_links = [{"image": ["4", 0]}]
    node = 10
    for filename in task["refs"]:
        graph_id = str(node)
        graph[str(node)] = {"class_type": "LoadImage", "inputs": {"image": filename}}
        image_links.append({"image": [graph_id, 0]})
        node += 1
    graph[str(node)] = {"class_type": "TextEncodeQwenImage21", "inputs": {
        "clip": ["2", 0], "prompt": STYLE + task["prompt"], "negative_prompt": "", "resolution": 1024,
        "images": image_links, "vae": ["3", 0]}}
    encode_id = str(node)
    graph[str(node + 1)] = {"class_type": "KSampler", "inputs": {
        "model": ["1", 0], "positive": [encode_id, 0], "negative": [encode_id, 1],
        "latent_image": [encode_id, 2], "seed": task["seed"], "steps": 35, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    graph[str(node + 2)] = {"class_type": "VAEDecode", "inputs": {"samples": [str(node + 1), 0], "vae": ["3", 0]}}
    graph[str(node + 3)] = {"class_type": "SaveImage", "inputs": {
        "images": [str(node + 2), 0], "filename_prefix": f"Q21_STYLE_{task['name']}"}}
    request = urllib.request.Request(BASE + "/prompt", data=json.dumps({"prompt": graph}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        prompt_id = json.load(response)["prompt_id"]
    print(f"submitted {task['name']} {prompt_id}", flush=True)
    for _ in range(1200):
        history = get("/history/" + prompt_id)
        if prompt_id in history:
            item = history[prompt_id]
            status = item.get("status", {}).get("status_str")
            print(f"finished {task['name']} {status} {json.dumps(item.get('outputs', {}))[:300]}", flush=True)
            if status != "success":
                raise RuntimeError(f"Qwen generation failed for {task['name']}: {history[prompt_id]}")
            return
        time.sleep(2)
    raise TimeoutError(f"Qwen generation timed out: {task['name']}")


for task in TASKS:
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": task["file"]}},
    }
    run(task)
