import os
import argparse
import glob
import pandas as pd
import re

COLS_MIN  = ['drop_id', 'date', 'latitude', 'longitude', 'camera', 'n_frames', 'frame', 'time_s', 'time_after_t0', 'family', 'count', 'confidence']
COLS_FULL = ['campaign', 'location', 'site', 'latitude', 'longitude', 'drop_id', 'date',
             'camera', 'n_frames', 'frame', 'time_s', 'time_after_t0',
             'family', 'count', 'confidence',
             'habitat', 'visibility', 'depth']


def load_clap_time(clap_json_path):
    import json
    with open(clap_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return float(data.get("clap_time_s", 0.0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames',          required=True, dest='frames_dir')
    parser.add_argument('--classifications', required=True, dest='classifications_dir')
    parser.add_argument('--clap',            required=True, dest='clap_json')
    parser.add_argument('--output',          required=True, dest='output_file')
    parser.add_argument('--frame_interval',  type=float,    required=True)
    parser.add_argument('--start_delay',     type=float,    default=180.0)
    parser.add_argument('--cam_id',          required=True)
    parser.add_argument('--csv_mode',        default='full', choices=['minimum', 'full'])
    parser.add_argument('--campaign',        default='')
    parser.add_argument('--location',        default='')
    parser.add_argument('--site',            default='')
    parser.add_argument('--latitude',        default='')
    parser.add_argument('--longitude',       default='')
    parser.add_argument('--drop_id',         default='')
    parser.add_argument('--date',            default='')
    parser.add_argument('--habitat',         default='')
    parser.add_argument('--visibility',      default='')
    parser.add_argument('--depth',           default='')
    args = parser.parse_args()

    clap_time_s    = load_clap_time(args.clap_json)
    frame_interval = args.frame_interval
    if frame_interval <= 0:
        _info_path = os.path.join(args.frames_dir, 'frames_info.json')
        if os.path.isfile(_info_path):
            import json as _json
            with open(_info_path, encoding='utf-8') as _fh:
                frame_interval = _json.load(_fh).get('frame_interval', 0.0)
        if frame_interval <= 0:
            print("[WARN] frame_interval=0 and no frames_info.json found — timestamps will be wrong.")
    n_frames    = len(glob.glob(os.path.join(args.frames_dir, '*.jpg')))
    records = []

    for frame_path in sorted(glob.glob(os.path.join(args.frames_dir, '*.jpg'))):
        frame_name = os.path.basename(frame_path)
        frame_id   = os.path.splitext(frame_name)[0]

        match         = re.search(r'frame_(\d+)', frame_id)
        frame_num     = int(match.group(1)) if match else 0
        time_s        = clap_time_s + args.start_delay + (frame_num - 1) * frame_interval
        time_after_t0 = args.start_delay + (frame_num - 1) * frame_interval

        frame_class_dir = os.path.join(args.classifications_dir, frame_id)
        if not os.path.exists(frame_class_dir):
            continue

        for class_file in glob.glob(os.path.join(frame_class_dir, '*.txt')):
            try:
                with open(class_file, 'r', encoding='utf-8') as f:
                    first_line = f.readline()
                if not first_line:
                    continue

                parts      = first_line.split(':')
                family     = parts[0].strip()
                confidence = float(parts[1].strip())

                # 'fp' is not a family: it is the marker the Manual Correction
                # tab writes into the .txt for a detection rejected by a human.
                # Without this, re-running this script over corrected files
                # would turn every rejection into an observation of a fish
                # species called "fp".
                if family == 'fp':
                    continue

                record = {
                    'camera':        args.cam_id,
                    'n_frames':      n_frames,
                    'frame':         frame_num,
                    'time_s':        round(time_s, 2),
                    'time_after_t0': round(time_after_t0, 2),
                    'family':        family,
                    'count':         1,
                    'confidence':    round(confidence, 4),
                    'drop_id':       args.drop_id,
                    'date':          args.date,
                    'latitude':      args.latitude,
                    'longitude':     args.longitude,
                }
                if args.csv_mode == 'full':
                    record['campaign']   = args.campaign
                    record['location']   = args.location
                    record['site']       = args.site
                    record['habitat']    = args.habitat
                    record['visibility'] = args.visibility
                    record['depth']      = args.depth

                records.append(record)

            except Exception as e:
                print(f"[WARN] File ignored ({class_file}): {e}")

    cols = COLS_FULL if args.csv_mode == 'full' else COLS_MIN
    df   = pd.DataFrame(records, columns=cols) if records else pd.DataFrame(columns=cols)
    if not df.empty:
        df = df.sort_values(['frame', 'family']).reset_index(drop=True)

    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    df.to_csv(args.output_file, index=False)
    print(f"CSV saved to {args.output_file} — {len(df)} detections")


if __name__ == '__main__':
    main()
