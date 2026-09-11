"""
Crée une planche verticale multi-caméras pour un drop.

Usage :
  python3 make_planche.py <drop_name> [--results results] [--output path.png]

Les images viennent de :
  <results>/<drop_name>/<cam_id>_annotated/
"""

import os
import re
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont


LEFT_LABEL_WIDTH  = 170
TOP_HEADER_HEIGHT = 40
BG_COLOR     = (255, 255, 255)
TEXT_COLOR   = (0, 0, 0)
BORDER_COLOR = (160, 160, 160)

# Limites de sauvegarde pour la compatibilité des visionneuses
# PNG : seuil PIL 12.x = 89 Mpx ; on vise 50 Mpx pour être sous toutes les limites
_MAX_PNG_PIXELS  = 50_000_000
# PDF : dimension max en pixels pour obtenir une page ≤ A1 à 150 dpi
_MAX_PDF_DIM_PX  = 5_000

Image.MAX_IMAGE_PIXELS = None   # désactive la bombe PIL pendant la construction


def list_images(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png")))


def get_label(name):
    if not name:
        return ""
    if "clap" in name.lower():
        return "clap"
    m = re.search(r"t_(\d{2}-\d{2})", name)
    return f"t = {m.group(1).replace('-', ':')}" if m else ""


def load_font(size=18):
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _build_planche(camera_dirs, cam_ids, output_png, output_pdf):
    """
    camera_dirs : liste des dossiers {cam_id}_annotated (un par colonne)
    cam_ids     : liste des identifiants caméra (pour les en-têtes)
    """
    cams = [list_images(d) for d in camera_dirs]

    if not any(cams):
        raise RuntimeError("No annotated folder found.")

    missing = [cam_ids[i] for i, c in enumerate(cams) if not c]
    if missing:
        print(f"[WARN] Empty or missing annotated folders: {missing}")

    sample_path = None
    for d, imgs in zip(camera_dirs, cams):
        if imgs:
            sample_path = os.path.join(d, imgs[0])
            break
    sample = Image.open(sample_path).convert("RGB")
    w, h   = sample.size

    n_cols = len(cam_ids)
    rows   = max((len(c) for c in cams), default=0)
    if rows == 0:
        raise RuntimeError("No annotated images found in folders.")

    canvas = Image.new(
        "RGB",
        (LEFT_LABEL_WIDTH + n_cols * w, TOP_HEADER_HEIGHT + rows * h),
        BG_COLOR,
    )
    draw        = ImageDraw.Draw(canvas)
    font        = load_font(20)
    font_header = load_font(22)

    draw.rectangle([0, 0, LEFT_LABEL_WIDTH, TOP_HEADER_HEIGHT], outline=BORDER_COLOR, width=1)
    draw.text((10, 8), "Time", fill=TEXT_COLOR, font=font_header)

    # En-têtes des colonnes (cam_id)
    for i, cam_id in enumerate(cam_ids):
        x0 = LEFT_LABEL_WIDTH + i * w
        draw.rectangle([x0, 0, x0 + w, TOP_HEADER_HEIGHT], outline=BORDER_COLOR, width=1)
        draw.text((x0 + 10, 8), f"Cam {cam_id}", fill=TEXT_COLOR, font=font_header)

    # Lignes d'images
    for r in range(rows):
        y   = TOP_HEADER_HEIGHT + r * h
        ref = next((cams[c][r] for c in range(n_cols) if r < len(cams[c])), None)

        draw.rectangle([0, y, LEFT_LABEL_WIDTH, y + h], outline=BORDER_COLOR, width=1)
        draw.text((10, y + 20), get_label(ref), fill=TEXT_COLOR, font=font)

        for c in range(n_cols):
            x0 = LEFT_LABEL_WIDTH + c * w
            x1 = x0 + w
            draw.rectangle([x0, y, x1, y + h], outline=BORDER_COLOR, width=1)
            if r < len(cams[c]):
                img = Image.open(os.path.join(camera_dirs[c], cams[c][r])).convert("RGB")
                if img.size != (w, h):
                    img = img.resize((w, h), Image.LANCZOS)
                canvas.paste(img, (x0, y))
                draw.rectangle([x0, y, x1, y + h], outline=BORDER_COLOR, width=1)

    os.makedirs(os.path.dirname(output_png) or ".", exist_ok=True)

    # ── Sauvegarde PNG ────────────────────────────────────────────────────────
    # Redimensionner si la planche dépasse le seuil MAX_IMAGE_PIXELS des visionneuses
    # (eog, Shotwell, Nautilus utilisent gdk-pixbuf avec la même limite que PIL).
    total_px = canvas.width * canvas.height
    if total_px > _MAX_PNG_PIXELS:
        scale     = (_MAX_PNG_PIXELS / total_px) ** 0.5
        png_w     = max(1, int(canvas.width  * scale))
        png_h     = max(1, int(canvas.height * scale))
        png_img   = canvas.resize((png_w, png_h), Image.LANCZOS)
        print(f"[INFO] PNG resized: {canvas.width}x{canvas.height} -> {png_w}x{png_h} px "
              f"({png_w * png_h / 1e6:.1f} Mpx)")
    else:
        png_img = canvas
    png_img.save(output_png)

    # ── Sauvegarde PDF ────────────────────────────────────────────────────────
    # PIL génère un PDF en encapsulant l'image JPEG. À 300 dpi sur une planche
    # de 9770×27040 px, la page fait 82×229 cm → écran noir dans les visionneuses.
    # On cible max _MAX_PDF_DIM_PX px dans la plus grande dimension → page A1 à 150 dpi.
    max_dim = max(canvas.width, canvas.height)
    if max_dim > _MAX_PDF_DIM_PX:
        scale   = _MAX_PDF_DIM_PX / max_dim
        pdf_w   = max(1, int(canvas.width  * scale))
        pdf_h   = max(1, int(canvas.height * scale))
        pdf_img = canvas.resize((pdf_w, pdf_h), Image.LANCZOS)
        print(f"[INFO] PDF resized: {canvas.width}x{canvas.height} -> {pdf_w}x{pdf_h} px")
    else:
        pdf_img = canvas
    pdf_img.save(output_pdf, "PDF", resolution=150.0)

    print(f"Panel created:\n  {output_png}\n  {output_pdf}")


def _discover_cams(drop_dir):
    """Découvre les cam_ids depuis les dossiers {cam_id}_annotated existants."""
    cams = []
    for entry in sorted(os.listdir(drop_dir)):
        if entry.endswith("_annotated") and os.path.isdir(os.path.join(drop_dir, entry)):
            cams.append(entry[:-len("_annotated")])
    return cams


def main():
    parser = argparse.ArgumentParser(description="Crée la planche verticale d'un drop")
    parser.add_argument("drop_name", help="Nom du drop")
    parser.add_argument("--results", default="results", help="Dossier results")
    parser.add_argument("--output",  default=None,
                        help="Chemin PNG de sortie (défaut : results/<drop>/planche_verticale.png)")
    args = parser.parse_args()

    drop_dir    = os.path.join(args.results, args.drop_name)
    cam_ids     = _discover_cams(drop_dir)
    camera_dirs = [os.path.join(drop_dir, f"{c}_annotated") for c in cam_ids]

    output_png = args.output or os.path.join(drop_dir, "planche_verticale.png")
    output_pdf = os.path.splitext(output_png)[0] + ".pdf"

    _build_planche(camera_dirs, cam_ids, output_png, output_pdf)


if 'snakemake' in globals():
    _drop_name   = snakemake.params.drop_name
    _cam_ids     = snakemake.params.cam_ids
    _results_dir = snakemake.params.results_dir
    _drop_dir    = os.path.join(_results_dir, _drop_name)
    _camera_dirs = [os.path.join(_drop_dir, f"{c}_annotated") for c in _cam_ids]
    _build_planche(_camera_dirs, _cam_ids, snakemake.output.png, snakemake.output.pdf)
elif __name__ == "__main__":
    main()
