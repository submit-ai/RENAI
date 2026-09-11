import os
import argparse
import glob
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results_dir', required=True)
    parser.add_argument('--output',      required=True)
    args = parser.parse_args()

    drop_csvs = sorted(glob.glob(
        os.path.join(args.results_dir, '*', 'classification_drop.csv')
    ))

    if not drop_csvs:
        print("[WARN] No classification_drop.csv found in subfolders.")
        pd.DataFrame().to_csv(args.output, index=False)
        return

    dfs = []
    for f in drop_csvs:
        if os.path.getsize(f) > 0:
            try:
                d = pd.read_csv(f)
                if not d.empty:
                    dfs.append(d)
            except Exception as e:
                print(f"[WARN] Skipped ({os.path.basename(os.path.dirname(f))}): {e}")

    if dfs:
        result = pd.concat(dfs, ignore_index=True)
    else:
        result = pd.DataFrame()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Campaign CSV saved to {args.output} — "
          f"{len(result)} detections, {len(drop_csvs)} drops")


if __name__ == '__main__':
    main()
