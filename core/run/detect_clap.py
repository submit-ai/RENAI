import os
import sys
import json
import argparse
import cv2
import numpy as np


def find_video_file(video_path):
    if os.path.exists(video_path):
        return video_path

    base, ext = os.path.splitext(video_path)
    for e in [ext.lower(), ext.upper(), ext.capitalize()]:
        test_path = base + e
        if os.path.exists(test_path):
            return test_path

    if os.path.exists(base):
        return base

    raise FileNotFoundError(f"Video file not found: {video_path}")


def detect_clap_time(video_file, sample_every_n_frames=10, score_threshold=5.0):
    """Détecte le clap par la différence absolue entre frames consécutives.

    Retourne (clap_time_s, clap_detected).
    Si aucun événement de mouvement significatif n'est trouvé
    (score max < score_threshold), retourne (0.0, False) → fallback t=0.
    """
    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_file}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0

    prev_gray     = None
    scores        = []
    frame_indices = []
    frame_idx     = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % sample_every_n_frames != 0:
            frame_idx += 1
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None:
            diff  = cv2.absdiff(gray, prev_gray)
            score = float(np.mean(diff))
            scores.append(score)
            frame_indices.append(frame_idx)

        prev_gray  = gray
        frame_idx += 1

    cap.release()

    if not scores:
        return 0.0, False

    best_i     = int(np.argmax(scores))
    best_score = scores[best_i]

    if best_score < score_threshold:
        # Aucun événement de mouvement suffisamment marqué → pas de clap
        return 0.0, False

    clap_frame  = frame_indices[best_i]
    clap_time_s = clap_frame / fps
    return clap_time_s, True


def main():
    if 'snakemake' in globals():
        video_path   = snakemake.input.video
        output_json  = snakemake.output.clap_file
        score_threshold = float(snakemake.config.get('clap_threshold', 5.0))
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--video',     required=True)
        parser.add_argument('--output',    required=True)
        parser.add_argument('--threshold', type=float, default=5.0)
        args         = parser.parse_args()
        video_path   = args.video
        output_json  = args.output
        score_threshold = args.threshold

    video_file = find_video_file(video_path)
    os.makedirs(os.path.dirname(output_json), exist_ok=True)

    clap_time_s, clap_detected = detect_clap_time(
        video_file, score_threshold=score_threshold
    )

    if clap_detected:
        print(f"[OK]   Clap detected at {clap_time_s:.2f} s")
    else:
        print(f"[WARN] No clap detected (max score < {score_threshold}) "
              f"— using t=0 as time reference.")

    data = {
        "video_file":    video_file,
        "clap_time_s":   clap_time_s,
        "clap_detected": clap_detected,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Result written to: {output_json}")


if __name__ == "__main__":
    main()
