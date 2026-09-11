import os
import sys

# RF-DETR construit son backbone DINOv2 via `transformers.AutoBackbone.from_pretrained(
# "facebook/dinov2-base", ...)` à chaque instanciation, indépendamment du checkpoint
# fine-tuné local (`pretrain_weights`). Sans ça, RENAI dépend silencieusement d'un accès
# réseau à huggingface.co au runtime, ce qui échoue sur les postes à accès restreint
# (proxy/firewall institutionnel). On bundle donc un cache HuggingFace local pour ce
# modèle et on force le mode offline avant tout import de transformers/rfdetr.
_HF_CACHE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'models', 'detecteur', 'hf_cache',
))
os.environ.setdefault('HF_HOME', _HF_CACHE_DIR)
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import argparse
import torch
from PIL import Image
from rfdetr import RFDETRLarge
from pathlib import Path
import glob

os.environ["WANDB_DISABLED"] = "true"


def _load_model(model_path: str, use_cuda: bool) -> RFDETRLarge:
    """Charge RFDETRLarge sur GPU ou CPU.

    rfdetr détecte CUDA via torch.cuda.is_available() en interne.
    Pour forcer le CPU, on patch temporairement cette fonction.
    """
    if use_cuda:
        print("[GPU] Loading RF-DETR model on CUDA...")
        return RFDETRLarge(
            resolution=1008, num_queries=300, num_select=300,
            dec_layers=6, dropout=0.1, drop_path=0.1,
            pretrain_weights=model_path,
        )
    else:
        print("[CPU] Loading RF-DETR model on CPU...")
        _orig = torch.cuda.is_available
        torch.cuda.is_available = lambda: False
        try:
            return RFDETRLarge(
                resolution=1008, num_queries=300, num_select=300,
                dec_layers=6, dropout=0.1, drop_path=0.1,
                pretrain_weights=model_path,
            )
        finally:
            torch.cuda.is_available = _orig


def _run_detections(frame_paths: list, output_dir: str,
                    threshold: float, model_path: str, use_cuda: bool) -> int:
    """Charge le modèle et traite toutes les frames. Retourne le nb de détections."""
    model = _load_model(model_path, use_cuda)
    device_label = "GPU" if use_cuda else "CPU"
    detection_count = 0

    for frame_path in frame_paths:
        try:
            img = Image.open(frame_path)
        except Exception as e:
            print(f"[{device_label}] Skipping image: {frame_path} — {e}")
            continue

        with torch.no_grad():
            detections = model.predict(img, threshold=threshold)

        for box in detections.xyxy:
            x1, y1, x2, y2 = box
            crop      = img.crop(box)
            frame_name = Path(frame_path).stem
            crop_name  = f"{frame_name}_{int(x1)}_{int(y1)}_{int(x2)}_{int(y2)}.jpg"
            crop.save(os.path.join(output_dir, crop_name))
            detection_count += 1

    # Libérer la mémoire immédiatement après traitement
    del model
    if use_cuda and torch.cuda.is_available():
        torch.cuda.empty_cache()
        print("[GPU] CUDA memory released.")

    return detection_count


def main():
    if 'snakemake' in globals():
        input_dir  = snakemake.input.frame_dir
        output_dir = snakemake.output.crop_dir
        threshold  = snakemake.params.threshold
        model_path = snakemake.params.model_path
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('--input',      required=True)
        parser.add_argument('--output',     required=True)
        parser.add_argument('--threshold',  type=float, default=0.3)
        parser.add_argument('--model_path', required=True)
        args       = parser.parse_args()
        input_dir  = args.input
        output_dir = args.output
        threshold  = args.threshold
        model_path = args.model_path

    os.makedirs(output_dir, exist_ok=True)

    image_exts  = {'.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG'}
    frame_paths = [
        p for p in glob.glob(os.path.join(input_dir, '*'))
        if os.path.splitext(p)[1].lower() in image_exts
        and not os.path.basename(p).startswith('.')
    ]

    if not frame_paths:
        print(f"No images found in {input_dir}")
        open(os.path.join(output_dir, ".processed"), 'a').close()
        sys.exit(0)

    print(f"Processing {len(frame_paths)} frames from {input_dir}")

    use_cuda = torch.cuda.is_available()
    if use_cuda:
        free_mb = torch.cuda.mem_get_info()[0] // (1024 ** 2)
        print(f"[GPU] {torch.cuda.get_device_name(0)} - {free_mb} MB libres")
    else:
        print("[CPU] No CUDA GPU available.")

    try:
        count = _run_detections(frame_paths, output_dir, threshold, model_path, use_cuda)

    except Exception as exc:
        is_oom = (
            isinstance(exc, torch.cuda.OutOfMemoryError)
            or (isinstance(exc, RuntimeError) and "CUDA out of memory" in str(exc))
        )
        if use_cuda and is_oom:
            print(f"[GPU OOM] {exc}")
            print("[GPU OOM -> fallback CPU] Reloading on CPU, please wait...")
            torch.cuda.empty_cache()
            count = _run_detections(
                frame_paths, output_dir, threshold, model_path, use_cuda=False
            )
        else:
            raise

    print(f"{count} detections saved to {output_dir}")
    open(os.path.join(output_dir, ".processed"), 'a').close()


if __name__ == '__main__':
    main()
