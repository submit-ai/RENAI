import os
import json
import argparse
import cv2


def find_video_file(video_path):
    if os.path.exists(video_path):
        return video_path

    base, ext = os.path.splitext(video_path)
    possible_exts = [ext.lower(), ext.upper(), ext.capitalize()]

    for e in possible_exts:
        test_path = base + e
        if os.path.exists(test_path):
            return test_path

    if os.path.exists(base):
        return base

    raise FileNotFoundError(f"Video file not found: {video_path}")


def load_clap_time(clap_json_path):
    with open(clap_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return float(data.get("clap_time_s", 0.0))


def main():
    if 'snakemake' in globals():
        video_path     = snakemake.input.video
        clap_json      = snakemake.input.clap
        output_dir     = snakemake.output.frame_dir
        frame_interval = snakemake.params.interval
        start_delay    = snakemake.params.start_delay
        max_frames     = getattr(snakemake.params, 'max_frames', 0)
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--video',        required=True)
        parser.add_argument('--clap',         required=True)
        parser.add_argument('--output',       required=True)
        parser.add_argument('--interval',     type=float, default=0.0)
        parser.add_argument('--start_delay',  type=float, default=0.0)
        parser.add_argument('--max_frames',   type=int,   default=0)
        args           = parser.parse_args()
        video_path     = args.video
        clap_json      = args.clap
        output_dir     = args.output
        frame_interval = args.interval
        start_delay    = args.start_delay
        max_frames     = args.max_frames

    if frame_interval <= 0 and max_frames <= 0:
        raise ValueError("At least one of --interval or --max_frames must be set.")

    video_file = find_video_file(video_path)
    os.makedirs(output_dir, exist_ok=True)

    clap_time_s  = load_clap_time(clap_json)
    start_time_s = clap_time_s + float(start_delay)

    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_file}")

    total_frames   = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    fps_video      = cap.get(cv2.CAP_PROP_FPS)
    video_duration = total_frames / fps_video if fps_video > 0 else float('inf')

    # Mode 3: max_frames only — auto-compute interval
    if frame_interval <= 0 and max_frames > 0:
        available = video_duration - start_time_s
        if available <= 0:
            raise ValueError(f"start_delay ({start_delay}s) >= video duration ({video_duration:.1f}s).")
        frame_interval = available / max_frames
        print(f"Auto-interval: {frame_interval:.2f}s ({max_frames} frames over {available:.1f}s)")

    print(f"Video       : {video_file}")
    print(f"Clap at     : {clap_time_s:.2f}s")
    print(f"Start at    : {start_time_s:.2f}s")
    print(f"Duration    : {video_duration:.2f}s")
    print(f"Interval    : {frame_interval:.2f}s")
    print(f"Max frames  : {max_frames if max_frames > 0 else 'unlimited'}")
    print(f"Output      : {output_dir}")

    frame_num = 1
    t = start_time_s

    while t < video_duration:
        if max_frames > 0 and frame_num > max_frames:
            break

        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if not ret:
            break

        output_path = os.path.join(output_dir, f"frame_{frame_num:06d}.jpg")
        cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        print(f"  frame_{frame_num:06d}.jpg @ {t:.2f}s")

        frame_num += 1
        t += frame_interval

    cap.release()
    print(f"Frames extracted: {frame_num - 1} → {output_dir}")

    import json
    info_path = os.path.join(output_dir, 'frames_info.json')
    with open(info_path, 'w', encoding='utf-8') as _f:
        json.dump({'frame_interval': frame_interval, 'n_frames': frame_num - 1}, _f)


if __name__ == "__main__":
    main()
