"""Assemble the sequential EP02 market bridge with the existing rough cut."""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg


def main():
    project = Path(__file__).resolve().parents[1] / "projects" / "美食：全市巡摆，馋哭食客"
    out = project / "outputs"
    sources = [
        out / "EP02_visual_rough_cut_with_h3_audio_v1.mp4",
        out / "EP02_SCN03_BR01_market_arrival" / "EP02_SCN03_BR01_market_arrival_h3_00001_.mp4",
        out / "EP02_SCN03_BR02_stall_stop" / "EP02_SCN03_BR02_stall_stop_h3_00001_.mp4",
        out / "EP02_SCN03_BR03_dismount" / "EP02_SCN03_BR03_dismount_h3_00001_.mp4",
    ]
    target = out / "EP02_market_arrival_bridge_with_h3_audio_v3.mp4"
    manifest = out / "EP02_market_arrival_bridge_with_h3_audio_v3.json"
    if target.exists() or manifest.exists():
        raise SystemExit("Refusing to overwrite existing assembly")
    for source in sources:
        if not source.exists():
            raise SystemExit(f"Missing input: {source}")

    # BR02 and BR03 each begin with the preceding shot's exact sampled frame.
    # Drop that duplicated first frame in the assembly.
    segments = [
        (0, "trim=start_frame=0:end_frame=192", "atrim=start=0:end=8"),
        (1, "trim=start_frame=0:end_frame=81", "atrim=start=0:end=3.375"),
        (2, "trim=start_frame=1:end_frame=107", "atrim=start=0.041666667:end=4.458333"),
        (3, "trim=start_frame=1:end_frame=107", "atrim=start=0.041666667:end=4.458333"),
        (0, "trim=start_frame=192", "atrim=start=8"),
    ]
    filters = []
    for n, (src, vf, af) in enumerate(segments):
        filters.append(f"[{src}:v]{vf},setpts=PTS-STARTPTS,fps=24,format=yuv420p,setsar=1[v{n}]")
        filters.append(f"[{src}:a]{af},asetpts=PTS-STARTPTS,aresample=32000[a{n}]")
    tags = "".join(f"[v{n}][a{n}]" for n in range(len(segments)))
    filters.append(f"{tags}concat=n={len(segments)}:v=1:a=1[v][a]")
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    for source in sources:
        command.extend(["-i", str(source)])
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-t", "73.583333",
        "-movflags", "+faststart", str(target),
    ])
    subprocess.run(command, check=True)
    manifest.write_text(json.dumps({
        "output": str(target.relative_to(project)).replace("\\", "/"),
        "sources": [str(p.relative_to(project)).replace("\\", "/") for p in sources],
        "edit": [
            "old cut frames 0-191",
            "BR01 frames 0-80 (the chosen entry handoff)",
            "BR02 frames 1-106 (duplicate first frame omitted)",
            "BR03 frames 1-106 (duplicate first frame omitted)",
            "old cut frames 192-end",
        ],
        "fps": 24,
        "selected_video_frames": 1766,
        "audio": "Retains the H3 audio of each included segment; existing speech quality is not corrected.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
