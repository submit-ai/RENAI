"""
Valide la cohérence entre planche_verticale.png et metadata.json.

Erreurs (bloquantes — exit 1) :
  - dimensions PNG ≠ dimensions reportées dans le metadata
  - n_columns ≠ len(camera_order)

Warnings (non bloquants — exit 0) :
  - camera_id non-entier dans les cellules
  - champs planche_id / site_id absents

Usage CLI :
  python3 validate_planche.py <png_path> <json_path>
"""

import os
import sys
import json
import argparse
from PIL import Image


# Tolérance d'arrondi : round() sur scale × constante peut donner ±1 px par terme.
# On accepte n_cols + 1 pixels d'écart sur la largeur, n_rows + 1 sur la hauteur.
_TOL_EXTRA = 1


def validate(png_path: str, json_path: str) -> tuple[list[str], list[str]]:
    """
    Retourne (errors, warnings).
    errors   → pipeline doit échouer
    warnings → loggés mais pipeline continue
    """
    errors   = []
    warnings = []

    # ── Chargement des fichiers ───────────────────────────────────────────────
    try:
        png = Image.open(png_path)
        png_w, png_h = png.size
        png.close()
    except Exception as e:
        errors.append(f"Cannot open PNG ({png_path}): {e}")
        return errors, warnings

    try:
        with open(json_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as e:
        errors.append(f"Cannot read metadata.json ({json_path}): {e}")
        return errors, warnings

    n_cols       = meta.get("n_columns",         0)
    n_rows       = meta.get("n_rows",            0)
    cell_w       = meta.get("cell_width",         0)
    cell_h       = meta.get("cell_height",        0)
    label_w      = meta.get("left_label_width",   0)
    header_h     = meta.get("top_header_height",  0)
    camera_order = meta.get("camera_order",       [])
    cells        = meta.get("cells",              [])

    # ── Check 1 : largeur PNG ─────────────────────────────────────────────────
    expected_w = label_w + n_cols * cell_w
    tol_w      = n_cols + _TOL_EXTRA
    if abs(png_w - expected_w) > tol_w:
        errors.append(
            f"PNG width ({png_w}px) != left_label_width + n_columns x cell_width "
            f"({label_w} + {n_cols}x{cell_w} = {expected_w}px)  [diff={png_w - expected_w:+d}px]"
        )

    # ── Check 2 : hauteur PNG ─────────────────────────────────────────────────
    expected_h = header_h + n_rows * cell_h
    tol_h      = n_rows + _TOL_EXTRA
    if abs(png_h - expected_h) > tol_h:
        errors.append(
            f"PNG height ({png_h}px) != top_header_height + n_rows x cell_height "
            f"({header_h} + {n_rows}x{cell_h} = {expected_h}px)  [diff={png_h - expected_h:+d}px]"
        )

    # ── Check 3 : n_columns == len(camera_order) ─────────────────────────────
    if n_cols != len(camera_order):
        errors.append(
            f"n_columns ({n_cols}) ≠ len(camera_order) ({len(camera_order)}) : {camera_order}"
        )

    # ── Check 4 : camera_id entier dans toutes les cellules ──────────────────
    non_int = [(c.get("camera_id"), c.get("image_id", "?"))
               for c in cells if not isinstance(c.get("camera_id"), int)]
    if non_int:
        examples = ", ".join(f"{v!r} ({img})" for v, img in non_int[:5])
        warnings.append(
            f"camera_id non-entier dans {len(non_int)} cellule(s) — exemples : {examples}"
        )

    # ── Check 5 : champs obligatoires ────────────────────────────────────────
    for field in ("planche_id", "site_id"):
        if field not in meta:
            warnings.append(f"Missing metadata field: '{field}'")

    return errors, warnings


def run(png_path: str, json_path: str) -> bool:
    """Affiche les résultats et retourne True si tout est valide (pas d'erreur)."""
    errors, warnings = validate(png_path, json_path)

    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}", file=sys.stderr)

    if not errors and not warnings:
        try:
            with open(json_path, encoding="utf-8") as f:
                meta = json.load(f)
            print(
                f"[OK] Panel validation: "
                f"{meta.get('n_columns')} col × {meta.get('n_rows')} rows — "
                f"cell {meta.get('cell_width')}×{meta.get('cell_height')}px"
            )
        except Exception:
            print("[OK] Panel validation successful.")
    elif not errors:
        print("[OK] Panel validation successful (with warnings).")

    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(description="Valide PNG ↔ metadata.json")
    parser.add_argument("png_path",  help="Chemin vers planche_verticale.png")
    parser.add_argument("json_path", help="Chemin vers metadata.json")
    args = parser.parse_args()

    ok = run(args.png_path, args.json_path)
    sys.exit(0 if ok else 1)


if 'snakemake' in globals():
    ok = run(snakemake.input.png, snakemake.input.json)
    if ok:
        # Écriture du marker uniquement si la validation réussit
        open(snakemake.output.marker, 'w').close()
    else:
        sys.exit(1)
elif __name__ == "__main__":
    main()
