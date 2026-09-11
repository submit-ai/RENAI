import os
import sys

# RADIO (nvidia/C-RADIOv3-H, trust_remote_code=True) est chargé depuis HuggingFace Hub
# au runtime, sans accès réseau garanti sur les postes à accès restreint (proxy/firewall
# institutionnel, ex. OFB). On bundle un cache HuggingFace local (poids + code distant)
# et on force le mode offline avant tout import de transformers/torch, comme pour le
# backbone dinov2-base de la Detection (voir core/run/detect_and_crop.py).
_HF_CACHE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'classifieur', 'hf_cache',
))
os.environ.setdefault('HF_HOME', _HF_CACHE_DIR)
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import argparse
import glob
import numpy as np
import joblib
from sklearn.preprocessing import LabelEncoder
from PIL import Image
from transformers import AutoModel, CLIPImageProcessor
import torch
import re


def resize_image(image):
    """Pad l'image au multiple de 16 requis par RADIO."""
    width, height = image.size
    if width % 16 == 0 and height % 16 == 0:
        return image
    img_array = np.array(image)
    avg_color = np.mean(img_array, axis=(0, 1)).astype(np.uint8)
    new_width  = ((width  + 15) // 16) * 16
    new_height = ((height + 15) // 16) * 16
    new_img = Image.new('RGB', (new_width, new_height), tuple(avg_color))
    new_img.paste(image, ((new_width - width) // 2, (new_height - height) // 2))
    return new_img


def get_embedding(image, processor, model, device):
    img = resize_image(image)
    pixel_values = processor(
        images=img, return_tensors='pt', do_resize=False
    ).pixel_values.to(device)
    with torch.no_grad():
        summary, _ = model(pixel_values)
    return summary[0].cpu().numpy().tolist()


def main():
    if 'snakemake' in globals():
        detections_dir = snakemake.input.detections_dir
        output_dir     = snakemake.output.classifications_dir
        model_path     = snakemake.params.model_path
        radio_model    = snakemake.params.radio_model
        min_surface    = snakemake.params.min_surface
        min_dim        = snakemake.params.min_dim
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--detections',  required=True, dest='detections_dir')
        parser.add_argument('--output',      required=True, dest='output_dir')
        parser.add_argument('--model_path',  required=True)
        parser.add_argument('--radio_model', required=True)
        parser.add_argument('--min_surface', type=int, required=True)
        parser.add_argument('--min_dim',     type=int, required=True)
        args           = parser.parse_args()
        detections_dir = args.detections_dir
        output_dir     = args.output_dir
        model_path     = args.model_path
        radio_model    = args.radio_model
        min_surface    = args.min_surface
        min_dim        = args.min_dim

    # ── Chargement des modèles communs (CPU-only, légers) ────────
    mlp_model  = joblib.load(model_path)
    scaler     = joblib.load(os.path.join(os.path.dirname(model_path), 'scaler.joblib'))
    pca        = joblib.load(os.path.join(os.path.dirname(model_path), 'pca.joblib'))
    le         = LabelEncoder()
    le.classes_ = np.load(
        os.path.join(os.path.dirname(model_path), 'label_encoder.npy'),
        allow_pickle=True,
    )
    families = le.classes_.tolist()

    # ── Détections à classer ──────────────────────────────────
    os.makedirs(output_dir, exist_ok=True)
    image_exts = {'.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'}
    detection_files = [
        p for p in glob.glob(os.path.join(detections_dir, '*'))
        if os.path.splitext(p)[1].lower() in image_exts
    ]

    if not detection_files:
        print("No detections found.")
        return

    print(f"Processing {len(detection_files)} detections...")

    def _run_classify(use_cuda: bool):
        device = torch.device("cuda" if use_cuda else "cpu")
        if use_cuda:
            free_mb = torch.cuda.mem_get_info()[0] // (1024 ** 2)
            print(f"[GPU] Loading RADIO on {torch.cuda.get_device_name(0)}"
                  f" - {free_mb} MB free")
        else:
            print("[CPU] Loading RADIO on CPU (no CUDA GPU available)")

        processor = CLIPImageProcessor.from_pretrained(radio_model)
        radio_mdl = AutoModel.from_pretrained(
            radio_model, trust_remote_code=True
        ).eval().to(device)

        for img_path in detection_files:
            try:
                filename = os.path.basename(img_path)
                coords   = re.findall(r'_(\d+)_(\d+)_(\d+)_(\d+)\.', filename)
                if not coords:
                    continue

                x1, y1, x2, y2 = map(int, coords[0])
                width   = x2 - x1
                height  = y2 - y1
                surface = width * height

                if surface < min_surface or width < min_dim or height < min_dim:
                    print(f"Skipping small detection: {filename} ({surface}px)")
                    continue

                img       = Image.open(img_path).convert('RGB')
                embedding = get_embedding(img, processor, radio_mdl, device)

                X      = pca.transform(scaler.transform([embedding]))
                probas = mlp_model.predict_proba(X)[0]

                sorted_indices  = np.argsort(probas)[::-1]
                sorted_families = [families[i] for i in sorted_indices]
                sorted_probas   = [probas[i]   for i in sorted_indices]

                match    = re.search(r'(frame_\d+)', filename)
                frame_id = match.group(1) if match else "unknown_frame"

                frame_class_dir = os.path.join(output_dir, frame_id)
                os.makedirs(frame_class_dir, exist_ok=True)

                detection_id = os.path.splitext(filename)[0]
                output_file  = os.path.join(frame_class_dir, f"{detection_id}.txt")

                with open(output_file, 'w', encoding='utf-8') as f:
                    for family, proba in zip(sorted_families, sorted_probas):
                        f.write(f"{family}: {proba:.4f}\n")

            except Exception as e:
                print(f"[WARN] Error processing {img_path}: {str(e)}")

        del radio_mdl, processor
        if use_cuda and torch.cuda.is_available():
            torch.cuda.empty_cache()
            print("[GPU] CUDA memory released.")

    use_cuda = torch.cuda.is_available()
    try:
        _run_classify(use_cuda)
    except Exception as exc:
        is_oom = (
            isinstance(exc, torch.cuda.OutOfMemoryError)
            or (isinstance(exc, RuntimeError) and "CUDA out of memory" in str(exc))
        )
        if use_cuda and is_oom:
            print(f"[GPU OOM] {exc}")
            print("[GPU OOM -> fallback CPU] Reloading RADIO on CPU, please wait...")
            torch.cuda.empty_cache()
            _run_classify(use_cuda=False)
        else:
            raise


if __name__ == '__main__':
    main()
