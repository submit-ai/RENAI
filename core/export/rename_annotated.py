"""
Renomme les images annotées d'une caméra dans un drop.

CLI : python rename_annotated.py <cam_id> <drop_name> [results_dir]
"""

import os
import re
import json
import sys
import cv2


def extract_frame_number(name: str):
    m = re.search(r"frame_(\d+)\.jpg$", name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def format_mmss(seconds: float):
    total = int(round(seconds))
    return f"{total // 60:02d}-{total % 60:02d}"


def load_clap_info(json_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    video_file = data.get("video_file")
    if not video_file:
        raise RuntimeError(f"video_file absent dans {json_path}")

    for key in ["clap_time_s", "clap_time", "clap_time_sec", "clap_sec", "time_sec", "time"]:
        if key in data:
            return float(data[key]), video_file

    raise RuntimeError(f"clap_time absent dans {json_path}")


def extract_clap_image(video_path: str, clap_time: float, output_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        raise RuntimeError(f"Invalid FPS for {video_path}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(clap_time * fps))))
    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        raise RuntimeError(f"Cannot extract clap from {video_path}")
    if not cv2.imwrite(output_path, frame):
        raise RuntimeError(f"Cannot save to {output_path}")


def process_cam(cam_id: str, drop_name: str, results_dir: str = "results",
               frame_interval: float = 30.0, start_delay: float = 180.0):
    drop_dir      = os.path.join(results_dir, drop_name)
    annotated_dir = os.path.join(drop_dir, f"{cam_id}_annotated")
    clap_json     = os.path.join(drop_dir, f"{cam_id}_clap.json")

    if not os.path.isdir(annotated_dir):
        print(f"[WARN] Directory not found: {annotated_dir}")
        return
    if not os.path.isfile(clap_json):
        print(f"[WARN] File not found: {clap_json}")
        return

    clap_time, video_file = load_clap_info(clap_json)

    if frame_interval <= 0:
        _info_path = os.path.join(drop_dir, f"{cam_id}_frames", 'frames_info.json')
        if os.path.isfile(_info_path):
            with open(_info_path, encoding='utf-8') as _f:
                frame_interval = json.load(_f).get('frame_interval', 0.0)
        if frame_interval <= 0:
            print(f"[WARN] frame_interval=0 — timestamps may be wrong.")

    files = sorted(f for f in os.listdir(annotated_dir) if f.lower().endswith(".jpg"))
    if not files:
        print(f"[WARN] No images found in {annotated_dir}")
        return

    clap_target = os.path.join(annotated_dir, "t_00-00_clap.jpg")
    extract_clap_image(video_file, clap_time, clap_target)
    print(f"[OK] Clap extracted: {clap_target}")

    frame_files = []
    for f in files:
        if f == "t_00-00_clap.jpg":
            continue
        n = extract_frame_number(f)
        if n is not None:
            frame_files.append((n, f))
    frame_files.sort()

    for idx, (frame_num, old_name) in enumerate(frame_files, start=1):
        rel_time = clap_time + start_delay + (frame_num - 1) * frame_interval
        new_name = f"t_{format_mmss(rel_time)}_f_{idx:03d}.jpg"
        old_path = os.path.join(annotated_dir, old_name)
        new_path = os.path.join(annotated_dir, new_name)

        if old_name == new_name:
            continue
        if os.path.exists(new_path):
            print(f"[SKIP] Already exists: {new_path}")
            continue
        os.rename(old_path, new_path)
        print(f"[OK] {old_name} -> {new_name}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--cam_id',         required=True)
    parser.add_argument('--drop_name',      required=True)
    parser.add_argument('--results_dir',    default='results')
    parser.add_argument('--frame_interval', type=float, default=30.0)
    parser.add_argument('--start_delay',    type=float, default=180.0)
    args = parser.parse_args()
    process_cam(args.cam_id, args.drop_name, args.results_dir,
                args.frame_interval, args.start_delay)
    print("\nDone.")


if 'snakemake' in globals():
    process_cam(
        snakemake.wildcards.cam_id,
        snakemake.params.drop_name,
        snakemake.params.results_dir,
        float(snakemake.params.frame_interval),
        float(snakemake.params.start_delay),
    )
    print("\nDone.")
elif __name__ == "__main__":
    main()
