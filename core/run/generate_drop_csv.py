import os
import argparse
import glob
import pandas as pd

COLS = ['drop_id', 'date', 'latitude', 'longitude', 'camera', 'n_frames', 'frame', 'time_s', 'family', 'genus', 'species', 'count', 'confidence']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drop_results', required=True)
    parser.add_argument('--output',       required=True)
    args = parser.parse_args()

    cam_csvs = sorted(
        glob.glob(os.path.join(args.drop_results, 'csv', '*_classification.csv'))
    )

    if not cam_csvs:
        print("[WARN] No camera CSV found.")
        pd.DataFrame(columns=COLS).to_csv(args.output, index=False)
        return

    dfs = [pd.read_csv(f) for f in cam_csvs if os.path.getsize(f) > 0]
    dfs = [d for d in dfs if not d.empty]

    if dfs:
        result = (
            pd.concat(dfs, ignore_index=True)
            .sort_values(['camera', 'frame', 'family'])
            .reset_index(drop=True)
        )
    else:
        result = pd.DataFrame(columns=COLS)

    result.to_csv(args.output, index=False)
    print(f"Drop CSV saved to {args.output} — {len(result)} detections")


if __name__ == '__main__':
    main()
