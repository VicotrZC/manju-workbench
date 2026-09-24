"""Export selected source frames for shot QA."""
import sys
from pathlib import Path

import cv2

video = Path(sys.argv[1])
output = Path(sys.argv[2])
indices = [int(value) for value in sys.argv[3:]]
output.mkdir(parents=True, exist_ok=True)
capture = cv2.VideoCapture(str(video))
if not capture.isOpened():
    raise SystemExit(f"cannot open video: {video}")
count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
if any(not 0 <= index < count for index in indices):
    raise SystemExit(f"requested frame outside 0..{count - 1}")
targets = set(indices)
for index in range(max(targets, default=-1) + 1):
    ok, frame = capture.read()
    if not ok:
        raise SystemExit(f"failed to decode frame {index}")
    if index in targets:
        destination = output / f"{video.stem.split('_h3_')[0]}_n{index:03d}.png"
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            raise SystemExit(f"failed to write {destination}")
        destination.write_bytes(encoded.tobytes())
        print(destination)
capture.release()
