# RENAI

**Underwater video processing pipeline**  
Automatic fish detection and classification from drop camera videos (DOP protocol, Martinique).

---

## Requirements

- Windows 10/11 64-bit
- NVIDIA GPU recommended (≥ 4 GB VRAM) — CPU mode supported but slower
- ~10 GB free disk space

---

## Installation

Download **`RENAI_Setup_v1.3.0.exe`** (~3.5 GB, includes all bundled ML models) from the Zenodo archive, then run it.

> **For peer review:** the Zenodo archive is accessible through the link provided with the manuscript. The archive is not yet published, so its DOI is reserved but not yet resolvable; a permanent DOI will be active upon publication.

The installer handles everything: Python environment, PyTorch (CUDA 11.8), all dependencies, and models. No manual setup required.

> **Note:** All models (RF-DETR, DINOv2, C-RADIO v3-H) are bundled in the installer — no network access needed at runtime.

---

## Usage

Launch RENAI from the Start menu or desktop shortcut.

### 1 — Select a drop folder

- **Single drop**: select a folder containing video files directly (`.mp4 / .mov / .avi / .mkv`). Each file = one camera.
- **Campaign mode**: select a parent folder whose subfolders are individual drops. RENAI processes them sequentially and generates a combined campaign Excel at the end.

### 2 — Fill in metadata

Campaign, Location, Site, Drop ID, Date, GPS coordinates, Habitat, Visibility, Depth.  
Metadata is saved automatically as `drop_metadata.json` in `results/<drop_name>/`.

### 3 — Set parameters

| Parameter | Default | Description |
|---|---|---|
| Delay after clap/start (s) | 0 | Seconds to skip at the start of each video |
| Frame interval (s) | 1 | One frame extracted every N seconds |
| Max frames (optional) | — | If set with interval: stops at N frames. If interval is empty: auto-calculates interval to extract exactly N frames evenly across the video |
| CSV format | Full | Full: all metadata columns. Minimum: detection columns only |

### 4 — Output options ▾

- **Export annotations**: saves bounding boxes in YOLO, COCO, or both formats
- **HTML report**: generates a self-contained `report.html` with Gallery and Frames tabs, including a correction mode to export training data

### 5 — Run

| Button | Action |
|---|---|
| **Start All** | Full 10-step pipeline (detection → classification → CSV → Excel → exports) |
| **Start Detection Only** | Steps 1–6 only (no CSV/Excel). Useful to inspect detections first |
| **Stop** | Interrupt after the current step |
| **Open Results** | Open the results folder in Explorer |

Click **?** in the top-right corner for the full in-app user guide.

---

## Manual Correction tab

The **Manual Correction** tab lets you review and correct pipeline output directly from the app — no need to edit CSVs by hand.

### Opening a drop or campaign
- Click **Open for correction ···** and select a drop results folder.
- For a full campaign, select the parent campaign folder — RENAI detects the structure and populates the Drop selector.
- When switching drops in campaign mode, a **metadata summary popup** appears with the key fields of the target drop (site, date, habitat, depth…). Click **Load drop** to proceed or **Cancel** to stay.

### Correcting classifications
- Navigate frames with **← Prev. / Next →** (or ⏮ ⏭ to jump to frames with detections).
- Click a bounding box to select it; the side panel shows **Family** and **Species** dropdowns.
- Use **✓ Valid** / **✗ False positive** to confirm or exclude a detection.
- Draw new detections with **✎ Bbox** (drag on canvas, then choose a family).
- **Ctrl+Z** (or ↩) to undo the last action.

### Saving
**💾 Save** rewrites all camera CSVs (with genus/species), updates the raw `.txt` classification files, and regenerates `classification_drop.csv / .xlsx`. If a campaign is loaded, it also regenerates the campaign-level files.

### Editing metadata
**✎ Metadata** opens a popup editor for all 10 metadata fields (Campaign, Location, Site, Date, GPS, Habitat, Visibility, Depth). Saving patches `drop_metadata.json` and all output files — useful for correcting metadata without re-running the pipeline.

### Exporting crops for retraining
**📤 Export crops** exports all valid detections (≥ 64×64 px) as PNG files, organised by family, into a folder of your choice. These crops can be used to retrain the classification model.

---

## Habitats characterization tab

The **Habitats characterization** tab is a read-only viewer for manually assessing a drop's surrounding habitat — a foundation for a future AI-based habitat classifier.

- Click **Open ···** and select a drop or campaign folder, same as Manual Correction. Switch drops with the **Drop** selector.
- RENAI builds a horizontal "360°" strip by taking the **middle frame** (50% through the recording) of each camera's raw `{cam}_frames/` — the midpoint is used instead of the first frame because some protocols clap on the boat before lowering the camera, so the very start of the video can show air/deck rather than the seafloor. Frames are shown clean, without detection boxes.
- The drop's recorded **Habitat** field (from `drop_metadata.json`) is displayed above the strip for comparison with what's visible.
- No editing, saving, zoom, or click interaction in this version — pure visualization.

---

## Results structure

```
results/
└── my_drop/
    ├── {cam_id}_frames/            ← extracted frames (.jpg)
    ├── {cam_id}_detections/        ← RF-DETR crops (.jpg, named frame_NNNNNN_x1_y1_x2_y2.jpg)
    ├── {cam_id}_annotated/         ← frames with bounding boxes
    ├── {cam_id}_classifications/   ← per-detection classification results
    ├── {cam_id}_annotations/       ← YOLO / COCO exports (if enabled)
    ├── csv/
    │   └── {cam_id}_classification.csv  ← per-camera classification table
    ├── classification_drop.csv     ← merged table (all cameras)
    ├── classification_drop.xlsx    ← Excel workbook (3 sheets):
    │   ├── Detections              ← one row per detection
    │   ├── Summary                 ← statistics by family and camera
    │   └── Indicators              ← TOFS, MeanCount, presence/absence per family
    ├── planche_verticale.png       ← composite vertical grid image
    ├── planche_verticale.pdf       ← same, PDF version
    ├── drop_metadata.json          ← user-filled metadata (campaign, GPS, habitat…)
    ├── metadata.json               ← grid structure descriptor
    └── report.html                 ← self-contained HTML report (if enabled)
```

---

## Models

| Model | Role | Size |
|---|---|---|
| RF-DETR Large | Fish detection | 1.55 GB |
| C-RADIO v3-H | Visual embedding extraction | 2.4 GB |
| PCA | Embedding normalization (3840 dim) | 56 MB |
| MLP classifier | Family-level classification | 38 MB |

The MLP classifier is trained on 9 families: Acanthuridae · Chaetodontidae · Haemulidae · Holocentridae · Labridae · Lutjanidae · Pomacentridae · Scaridae · Serranidae  
Excel outputs cover 12 families total, also including Carangidae · Scombridae · Sphyraenidae (manual correction only — not predicted by the model)

---

## Advanced configuration

Editable in `config.yaml`:

```yaml
start_delay         : 0    # delay (s) after clap before first frame
frame_interval      : 1    # seconds between extracted frames
clap_threshold      : 5.0  # minimum clap detection score
detection_threshold : 0.3  # detector confidence threshold (0–1)
results_dir         : results  # output folder (relative to RENAI root)
```

---

## Filling metadata in bulk

The app asks for a drop's metadata when it processes it. For a campaign already
on disk, `write_metadata.py` fills them from a field spreadsheet — one row per
site, matched on the `site` column:

```
python write_metadata.py --xlsx metadata_drop.xlsx \
                         --campaign-dir <folder holding one subfolder per drop> \
                         --results-dir  <the results/ folder>
```

It writes one `drop_metadata.json` per drop and lists the drops it could not
match, so a site missing from the spreadsheet is never filled in silently.

---

## Notes

- Tested on Windows 11, Python 3.10, PyTorch 2.6.0+cu118
- License: MIT

---

## Citation

This repository contains an anonymized version of RENAI, deposited for double-blind peer review.

- Code: this repository
- Packaged installer, model weights and third-party licences: Zenodo archive, accessible to
  reviewers through the link provided with the manuscript. Its DOI is reserved and will become
  resolvable upon publication.
