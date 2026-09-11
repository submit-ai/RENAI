"""
Génère le fichier metadata.json pour un drop multi-caméras.

Les dimensions (cell_width, cell_height, left_label_width, top_header_height)
sont lues depuis le PNG final sauvegardé par make_planche.py, garantissant
une cohérence exacte même si le PNG a été redimensionné.

Usage CLI :
  python3 make_metadata.py <drop_name> [--results results] [--output path.json] [--png path.png]
"""

import os
import re
import sys
import json
import argparse
from PIL import Image


# Doit correspondre aux constantes de make_planche.py
LEFT_LABEL_WIDTH  = 170
TOP_HEADER_HEIGHT = 40


def list_images(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png")))


def parse_image_info(filename):
    if "clap" in filename.lower():
        return {"frame_rank": 0, "time_seconds": 0, "time_label": "0min00"}

    m = re.match(r"t_(\d{2,})-(\d{2})_f_(\d{3,})\.jpg$", filename, re.IGNORECASE)
    if not m:
        return None

    mm, ss, rank = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return {
        "frame_rank":   rank,
        "time_seconds": mm * 60 + ss,
        "time_label":   f"{mm}min{ss:02d}",
    }


def _to_cam_id(c):
    """Retourne un int si le cam_id est numérique, sinon une string."""
    return int(c) if str(c).isdigit() else c


def _build_metadata(drop_name, cam_ids, results_dir, output_json, png_path):
    drop_dir    = os.path.join(results_dir, drop_name)
    camera_dirs = [os.path.join(drop_dir, f"{c}_annotated") for c in cam_ids]
    cams        = [list_images(d) for d in camera_dirs]
    n_cols      = len(cam_ids)

    if not any(cams):
        raise RuntimeError("No annotated folder found.")

    # ── Dimensions réelles depuis le PNG sauvegardé ───────────────────────────
    # make_planche.py peut avoir redimensionné le PNG (seuil 50 Mpx).
    # On relit le PNG final pour récupérer les vraies dimensions pixel.
    sample_path = next(
        (os.path.join(d, imgs[0]) for d, imgs in zip(camera_dirs, cams) if imgs),
        None,
    )
    if sample_path is None:
        raise RuntimeError("No annotated images found.")

    orig_w, orig_h = Image.open(sample_path).size

    if png_path and os.path.isfile(png_path):
        png_w, _ = Image.open(png_path).size
        # Scale appliqué par make_planche lors de la sauvegarde PNG
        canvas_w  = LEFT_LABEL_WIDTH + n_cols * orig_w
        scale     = png_w / canvas_w
    else:
        # Fallback : pas de PNG disponible (mode CLI sans PNG)
        scale = 1.0

    cell_width        = round(orig_w           * scale)
    cell_height       = round(orig_h           * scale)
    left_label_width  = round(LEFT_LABEL_WIDTH  * scale)
    top_header_height = round(TOP_HEADER_HEIGHT * scale)

    # ── Construction des lignes et cellules ───────────────────────────────────
    max_rows = max((len(c) for c in cams), default=0)
    rows  = []
    cells = []

    for r in range(max_rows):
        ref_name = next((cams[c][r] for c in range(n_cols) if r < len(cams[c])), None)
        if ref_name is None:
            continue
        info = parse_image_info(ref_name)
        if info is None:
            continue

        rows.append({
            "row":          r,
            "frame_rank":   info["frame_rank"],
            "time_seconds": info["time_seconds"],
            "time_label":   info["time_label"],
        })

        for c in range(n_cols):
            if r >= len(cams[c]):
                continue
            image_file = cams[c][r]
            image_info = parse_image_info(image_file)
            if image_info is None:
                continue

            cam_id   = _to_cam_id(cam_ids[c])
            image_id = f"{drop_name}_cam{cam_id}_t{image_info['time_seconds']}"

            cells.append({
                "row":          r,
                "col":          c,
                "camera_id":    cam_id,
                "frame_rank":   image_info["frame_rank"],
                "time_seconds": image_info["time_seconds"],
                "time_label":   image_info["time_label"],
                "image_id":     image_id,
                "image_file":   image_file,
            })

    camera_order = [_to_cam_id(c) for c in cam_ids]
    assert n_cols == len(camera_order), \
        f"Incohérence : n_columns={n_cols} ≠ len(camera_order)={len(camera_order)}"

    metadata = {
        "drop_id":           drop_name,
        "planche_id":        drop_name,
        "site_id":           "",
        "planche_file":      "planche_verticale.png",
        "n_columns":         n_cols,
        "n_rows":            len(rows),
        "cell_width":        cell_width,
        "cell_height":       cell_height,
        "left_label_width":  left_label_width,
        "top_header_height": top_header_height,
        "camera_order":      camera_order,
        "rows":              rows,
        "cells":             cells,
    }

    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Metadata created: {output_json}")
    print(f"  PNG scale   : {scale:.4f}  ({png_w}px / {canvas_w}px)" if scale != 1.0
          else "  PNG scale   : 1.0 (no resize)")
    print(f"  cell        : {cell_width}×{cell_height}px")
    print(f"  label/header: {left_label_width}px / {top_header_height}px")


def _discover_cams(drop_dir):
    cams = []
    for entry in sorted(os.listdir(drop_dir)):
        if entry.endswith("_annotated") and os.path.isdir(os.path.join(drop_dir, entry)):
            cams.append(entry[:-len("_annotated")])
    return cams


def main():
    parser = argparse.ArgumentParser(description="Génère le metadata.json d'un drop")
    parser.add_argument("drop_name", help="Nom du drop")
    parser.add_argument("--results", default="results", help="Dossier results")
    parser.add_argument("--output",  default=None,
                        help="Chemin JSON de sortie (défaut : results/<drop>/metadata.json)")
    parser.add_argument("--png",     default=None,
                        help="Chemin du PNG de la planche (pour lire les vraies dimensions)")
    args = parser.parse_args()

    drop_dir    = os.path.join(args.results, args.drop_name)
    cam_ids     = _discover_cams(drop_dir)
    output_json = args.output or os.path.join(drop_dir, "metadata.json")
    png_path    = args.png    or os.path.join(drop_dir, "planche_verticale.png")

    _build_metadata(args.drop_name, cam_ids, args.results, output_json, png_path)


if 'snakemake' in globals():
    _build_metadata(
        snakemake.params.drop_name,
        snakemake.params.cam_ids,
        snakemake.params.results_dir,
        snakemake.output.json,
        snakemake.input.png,
    )
elif __name__ == "__main__":
    main()
