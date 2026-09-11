"""
export_annotations.py
Export YOLO and/or COCO JSON annotations from RENAI pipeline outputs.

Sources:
  --frames_dir          : {drop_results}/{cam_id}_frames/
  --detections_dir      : {drop_results}/{cam_id}_detections/
  --classifications_dir : {drop_results}/{cam_id}_classifications/
  --output_dir          : {drop_results}/{cam_id}_annotations/
  --format              : yolo | coco | both
  --cam_id              : camera identifier (used in COCO filename)
"""
import os
import re
import json
import glob
import argparse
from PIL import Image


def _parse_crop_stem(stem):
    """Extract (frame_id, x1, y1, x2, y2) from crop filename stem."""
    m = re.match(r'(frame_\d+)_(\d+)_(\d+)_(\d+)_(\d+)', stem)
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))


def _top_family(cls_dir, frame_id, det_stem):
    """Return (family, confidence) from the classification txt file."""
    txt = os.path.join(cls_dir, frame_id, f"{det_stem}.txt")
    if not os.path.isfile(txt):
        return None, 0.0
    with open(txt, encoding='utf-8') as f:
        line = f.readline().strip()
    if ':' not in line:
        return None, 0.0
    fam, conf = line.split(':', 1)
    try:
        return fam.strip(), float(conf.strip())
    except ValueError:
        return fam.strip(), 0.0


def _frame_size(frames_dir, frame_id):
    """Return (width, height) from the frame image header (no pixel decode)."""
    for ext in ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'):
        p = os.path.join(frames_dir, f"{frame_id}{ext}")
        if os.path.isfile(p):
            with Image.open(p) as img:
                return img.size
    return None


def _build_detections(frames_dir, detections_dir, classifications_dir):
    """Collect all classified detections with frame size and bbox coords."""
    image_exts = {'.jpg', '.jpeg', '.png'}
    records = []

    for crop_path in sorted(glob.glob(os.path.join(detections_dir, '*'))):
        if os.path.splitext(crop_path)[1].lower() not in image_exts:
            continue
        stem = os.path.splitext(os.path.basename(crop_path))[0]
        parsed = _parse_crop_stem(stem)
        if not parsed:
            continue
        frame_id, x1, y1, x2, y2 = parsed

        size = _frame_size(frames_dir, frame_id)
        if not size:
            continue
        w_img, h_img = size

        family, confidence = _top_family(classifications_dir, frame_id, stem)
        if not family:
            continue

        records.append({
            'frame_id':   frame_id,
            'width':      w_img,
            'height':     h_img,
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'family':     family,
            'confidence': confidence,
        })

    return records


def export_yolo(detections, output_dir):
    yolo_dir = os.path.join(output_dir, 'yolo')
    os.makedirs(yolo_dir, exist_ok=True)

    families  = sorted(set(d['family'] for d in detections))
    class_idx = {f: i for i, f in enumerate(families)}

    with open(os.path.join(yolo_dir, 'classes.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(families))

    by_frame = {}
    for d in detections:
        by_frame.setdefault(d['frame_id'], []).append(d)

    for frame_id, dets in by_frame.items():
        w_img = dets[0]['width']
        h_img = dets[0]['height']
        lines = []
        for d in dets:
            cid = class_idx[d['family']]
            cx  = ((d['x1'] + d['x2']) / 2) / w_img
            cy  = ((d['y1'] + d['y2']) / 2) / h_img
            bw  = (d['x2'] - d['x1']) / w_img
            bh  = (d['y2'] - d['y1']) / h_img
            lines.append(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        with open(os.path.join(yolo_dir, f"{frame_id}.txt"), 'w') as f:
            f.write('\n'.join(lines))

    print(f"[YOLO] {len(by_frame)} label files + classes.txt → {yolo_dir}")


def export_coco(detections, output_dir, cam_id=''):
    families   = sorted(set(d['family'] for d in detections))
    categories = [{'id': i + 1, 'name': f, 'supercategory': 'fish'}
                  for i, f in enumerate(families)]
    cat_idx    = {f: i + 1 for i, f in enumerate(families)}

    frames_seen = {}
    for d in detections:
        if d['frame_id'] not in frames_seen:
            frames_seen[d['frame_id']] = {
                'id':        len(frames_seen) + 1,
                'file_name': f"{d['frame_id']}.jpg",
                'width':     d['width'],
                'height':    d['height'],
            }

    annotations = []
    for ann_id, d in enumerate(detections, 1):
        bw = d['x2'] - d['x1']
        bh = d['y2'] - d['y1']
        annotations.append({
            'id':          ann_id,
            'image_id':    frames_seen[d['frame_id']]['id'],
            'category_id': cat_idx[d['family']],
            'bbox':        [d['x1'], d['y1'], bw, bh],
            'area':        bw * bh,
            'iscrowd':     0,
            'score':       round(d['confidence'], 4),
        })

    coco = {
        'info':        {'description': 'RENAI annotations', 'version': '1.0'},
        'categories':  categories,
        'images':      list(frames_seen.values()),
        'annotations': annotations,
    }

    suffix   = f"_{cam_id}" if cam_id else ''
    out_file = os.path.join(output_dir, f"coco_annotations{suffix}.json")
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(coco, f, indent=2, ensure_ascii=False)

    print(f"[COCO] {len(annotations)} annotations → {out_file}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames_dir',          required=True)
    parser.add_argument('--detections_dir',      required=True)
    parser.add_argument('--classifications_dir', required=True)
    parser.add_argument('--output_dir',          required=True)
    parser.add_argument('--format', default='both', choices=['yolo', 'coco', 'both'])
    parser.add_argument('--cam_id', default='')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    detections = _build_detections(
        args.frames_dir, args.detections_dir, args.classifications_dir
    )

    if not detections:
        print("[ANNOT] No classified detections found — skipping.")
        return

    print(f"[ANNOT] {len(detections)} classified detections found.")
    if args.format in ('yolo', 'both'):
        export_yolo(detections, args.output_dir)
    if args.format in ('coco', 'both'):
        export_coco(detections, args.output_dir, cam_id=args.cam_id)


if __name__ == '__main__':
    main()
