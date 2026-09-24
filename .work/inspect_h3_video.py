"""Inspect video stream metadata and export representative source frames for review."""
import sys
from pathlib import Path

import cv2

video = Path(sys.argv[1])
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
capture = cv2.VideoCapture(str(video))
if not capture.isOpened():
    raise SystemExit(f"cannot open video: {video}")
fps = capture.get(cv2.CAP_PROP_FPS)
count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
print(f"video={video.name} size={width}x{height} fps={fps:.3f} frames={count} duration={count/fps:.3f}s")
indices = sorted(set([0, max(0, count // 2), max(0, count - 1)]))
for index in indices:
    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = capture.read()
    if not ok:
        raise SystemExit(f"failed to read frame {index}")
    path = output / f"S00_n{index:03d}.png"
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise SystemExit(f"failed to write {path}")
    path.write_bytes(encoded.tobytes())
    print(f"frame={index} time={index/fps:.3f}s path={path}")
capture.release()
