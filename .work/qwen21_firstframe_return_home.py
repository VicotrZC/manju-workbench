"""Create and stage the Qwen-Image 2.1 return-home camera-cut keyframe."""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "美食：全市巡摆，馋哭食客"
BASE = "http://127.0.0.1:8188"
OUT = PROJECT / "outputs" / "QWEN21_STYLE_V1"
OUT.mkdir(parents=True, exist_ok=True)
END_FRAME = OUT / "BR05_market_exit" / "BR05_market_exit_end_frame_n106.png"
OUTPUT = OUT / "Q21_KEYFRAME_S01_return_home_v1.png"
TAIL_REMOTE_NAME = "Q21_BR05_EXIT_END.png"
FRAME_REMOTE_NAME = "Q21_KEYFRAME_S01_return_home_v1.png"

sys.path.insert(0, str(ROOT / "ssh"))
from _target import password, target  # noqa: E402

if not END_FRAME.exists():
    raise SystemExit(f"missing selected BR05 end frame: {END_FRAME}")

host, port = target()
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, port=port, username="root", password=password(), timeout=25, banner_timeout=25, auth_timeout=25)
try:
    sftp = ssh.open_sftp()
    sftp.put(str(END_FRAME), f"/root/autodl-tmp/ComfyUI-qwen21/input/{TAIL_REMOTE_NAME}")
    sftp.close()
finally:
    ssh.close()

refs = [
    ("4", TAIL_REMOTE_NAME),
    ("5", "Q21_ASSET_STREET.png"),
    ("6", "Q21_ASSET_CHR01_BODY.png"),
    ("7", "Q21_ASSET_CHR01_FACE.png"),
    ("8", "Q21_ASSET_EBIKE.png"),
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
        "Create one wide cinematic 16:9 establishing frame for a contemporary Chinese animated drama, in the same polished, mature stylized 3D donghua look as the approved Qwen-Image 2.1 frames; clearly animated, softly sculpted adult face, refined animation shading and detailed materials, not live action. "
        "Use <image1> only to preserve the single rider, same blue-gray scooter and exactly one tied white pork parcel secured on the rear rack; discard its market background. Use <image2> as the fixed modern dawn residential street environment, preserving the tree-lined road, iron fences, sidewalk, street lamps and vanishing point. Use <image3> and <image4> for the exact young protagonist, black T-shirt, dark trousers, white sneakers, hairstyle and face. Use <image5> for the exact same scooter model, proportions, color and rack. "
        "The market trip is finished: show him riding away from camera along the same quiet residential street toward home, seen from a rear three-quarter view at natural road height. The one parcel is clearly visible, firmly strapped at the center of the rear rack, with no other cargo. Both hands hold the handlebars, natural seated posture, both wheels on the road. Predawn blue hour is beginning to brighten very slightly. Keep empty road and quiet neighborhood, one coherent scene. Exactly one rider, one scooter, one parcel. No market, no butcher stall, no extra bags, no basket, no other people or traffic, no signage, no text, no captions, no collage, no ancient or fantasy elements."
    ),
    "negative_prompt": "photorealistic live action, extra package, duplicate parcel, front basket, extra rider, extra vehicle, market stall, ancient clothing, fantasy, text, subtitles",
    "resolution": 1024,
    "images": [{"image": [node_id, 0]} for node_id, _ in refs],
    "vae": ["3", 0],
}}
graph["10"] = {"class_type": "EmptyLatentImage", "inputs": {"width": 1376, "height": 768, "batch_size": 1}}
graph["11"] = {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["10", 0], "seed": 920309, "steps": 35, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
graph["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}}
graph["13"] = {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "Q21_KEYFRAME_S01_return_home_v1"}}


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
        image = images[0]
        query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
        with urllib.request.urlopen(BASE + "/view?" + query, timeout=60) as response:
            OUTPUT.write_bytes(response.read())
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username="root", password=password(), timeout=25, banner_timeout=25, auth_timeout=25)
        try:
            sftp = ssh.open_sftp()
            sftp.put(str(OUTPUT), "/root/autodl-tmp/ComfyUI/input/" + FRAME_REMOTE_NAME)
            sftp.close()
        finally:
            ssh.close()
        print("saved and staged", OUTPUT, OUTPUT.stat().st_size, flush=True)
        break
    time.sleep(2)
else:
    raise SystemExit("timed out")
