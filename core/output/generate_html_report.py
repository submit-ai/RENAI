"""
generate_html_report.py
Generates an HTML visualization report for a RENAI drop.

Two views:
  Gallery -- crops grouped by family (filterable) + mode correction
  Frames  -- sub-tab per camera, all extracted frames shown;
            classified crops shown below frames that have detections.

Mode correction (Gallery only):
  Toggle the button to show a family selector on each crop card.
  Select the corrected family, click Ajouter.
  A fixed bottom bar lets you download a ZIP:
    training_corrections/{family}/{crop}.jpg  (PNG)
    training_corrections/yolo/classes.txt + {cam}_{frame}.txt  (YOLO)
    training_corrections/coco_corrections.json  (COCO)
    training_corrections/corrections_log.csv  (always)
  Requires JSZip (loaded from CDN -- internet connection needed for download).

Output: results/{drop_name}/report.html
"""
import os
import re
import json
import glob
import base64
import argparse

try:
    from PIL import Image as _PIL_Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


FAMILY_COLORS = {
    'acanthuridae':   '#1565C0',
    'carangidae':     '#0277BD',
    'chaetodontidae': '#6A1B9A',
    'haemulidae':     '#00695C',
    'holocentridae':  '#E65100',
    'labridae':       '#2E7D32',
    'lutjanidae':     '#C62828',
    'pomacentridae':  '#4527A0',
    'scaridae':       '#00838F',
    'scombridae':     '#558B2F',
    'serranidae':     '#AD1457',
    'sphyraenidae':   '#6D4C41',
}


def _scan_cameras(drop_results):
    """
    Returns dict: cam_id -> {frames: [{frame_id, frame_num, img_src, crops}]}
    Frames from *_annotated/ (renamed t_MM-SS_f_NNN.jpg by pipeline step 7).
    Crops matched via frame_{NNN:06d} lookup in *_detections/ + *_classifications/.
    """
    image_exts = {'.jpg', '.jpeg', '.png'}
    cameras = {}

    for ann_dir in sorted(glob.glob(os.path.join(drop_results, '*_annotated'))):
        cam_id  = os.path.basename(ann_dir).replace('_annotated', '')
        det_dir = os.path.join(drop_results, f"{cam_id}_detections")
        cls_dir = os.path.join(drop_results, f"{cam_id}_classifications")

        crops_by_frame = {}
        if os.path.isdir(det_dir):
            for crop_path in sorted(glob.glob(os.path.join(det_dir, '*'))):
                if os.path.splitext(crop_path)[1].lower() not in image_exts:
                    continue
                filename = os.path.basename(crop_path)
                stem     = os.path.splitext(filename)[0]
                m = re.match(r'(frame_\d+)_\d+_\d+_\d+_\d+', stem)
                if not m:
                    continue
                frame_id = m.group(1)

                family, confidence = None, 0.0
                txt_path = os.path.join(cls_dir, frame_id, f"{stem}.txt")
                if os.path.isfile(txt_path):
                    with open(txt_path, encoding='utf-8') as f:
                        line = f.readline().strip()
                    if ':' in line:
                        fam, conf = line.split(':', 1)
                        family = fam.strip()
                        try:
                            confidence = float(conf.strip())
                        except ValueError:
                            pass

                if not family:
                    continue

                crops_by_frame.setdefault(frame_id, []).append({
                    'src':    f"{cam_id}_detections/{filename}",
                    'family': family,
                    'conf':   round(confidence * 100, 1),
                })

        frames = []
        all_frame_files = []
        for ext in ('*.jpg', '*.jpeg', '*.png'):
            all_frame_files.extend(glob.glob(os.path.join(ann_dir, ext)))

        for frame_path in sorted(all_frame_files):
            filename = os.path.basename(frame_path)
            stem     = os.path.splitext(filename)[0]

            if stem.endswith('_clap'):
                frames.append({
                    'frame_id':  stem,
                    'frame_num': 0,
                    'img_src':   f"{cam_id}_annotated/{filename}",
                    'crops':     [],
                })
                continue

            m = re.search(r'_f_(\d+)$', stem)
            if not m:
                continue
            idx       = int(m.group(1))
            frame_key = f"frame_{idx:06d}"

            frames.append({
                'frame_id':  stem,
                'frame_num': idx,
                'img_src':   f"{cam_id}_annotated/{filename}",
                'crops':     crops_by_frame.get(frame_key, []),
            })

        if frames:
            cameras[cam_id] = {'frames': frames}

    return cameras


def _scan_detections_for_gallery(drop_results):
    """
    Flat list of classified detections for Gallery.
    Embeds each crop as base64 and parses bbox + frame dims for export.
    """
    image_exts = {'.jpg', '.jpeg', '.png'}
    records = []

    for det_dir in sorted(glob.glob(os.path.join(drop_results, '*_detections'))):
        cam_id  = os.path.basename(det_dir).replace('_detections', '')
        cls_dir = os.path.join(drop_results, f"{cam_id}_classifications")
        frm_dir = os.path.join(drop_results, f"{cam_id}_frames")

        for crop_path in sorted(glob.glob(os.path.join(det_dir, '*'))):
            if os.path.splitext(crop_path)[1].lower() not in image_exts:
                continue
            filename = os.path.basename(crop_path)
            stem     = os.path.splitext(filename)[0]
            m = re.match(r'(frame_(\d+))_(\d+)_(\d+)_(\d+)_(\d+)', stem)
            if not m:
                continue
            frame_id  = m.group(1)
            frame_num = int(m.group(2))
            x1, y1   = int(m.group(3)), int(m.group(4))
            x2, y2   = int(m.group(5)), int(m.group(6))

            family, confidence = None, 0.0
            txt_path = os.path.join(cls_dir, frame_id, f"{stem}.txt")
            if os.path.isfile(txt_path):
                with open(txt_path, encoding='utf-8') as f:
                    line = f.readline().strip()
                if ':' in line:
                    fam, conf = line.split(':', 1)
                    family = fam.strip()
                    try:
                        confidence = float(conf.strip())
                    except ValueError:
                        pass

            if not family:
                continue

            with open(crop_path, 'rb') as bf:
                b64 = base64.b64encode(bf.read()).decode('ascii')

            fw, fh = 0, 0
            if _HAS_PIL:
                for ext in ('.jpg', '.jpeg', '.png', '.JPG', '.JPEG'):
                    fp = os.path.join(frm_dir, f"{frame_id}{ext}")
                    if os.path.isfile(fp):
                        try:
                            with _PIL_Image.open(fp) as img:
                                fw, fh = img.size
                        except Exception:
                            pass
                        break

            records.append({
                'cam_id':     cam_id,
                'crop_file':  filename,
                'frame_id':   frame_id,
                'frame_num':  frame_num,
                'family':     family,
                'confidence': confidence,
                'b64':        b64,
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'fw': fw, 'fh': fh,
            })

    return records


def _compute_summary(records):
    summary = {}
    for r in records:
        fam = r['family']
        if fam not in summary:
            summary[fam] = {'count': 0, 'first_frame': float('inf')}
        summary[fam]['count'] += 1
        if r['frame_num'] < summary[fam]['first_frame']:
            summary[fam]['first_frame'] = r['frame_num']
    return summary


def _build_html(drop_name, records, summary, cameras, drop_results):
    all_families = sorted(set(r['family'] for r in records))
    all_cams     = sorted(cameras.keys())

    meta = {}
    meta_path = os.path.join(drop_results, 'drop_metadata.json')
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            pass

    meta_parts = []
    for key, label in [('date', 'Date'), ('site', 'Site'),
                       ('habitat', 'Habitat'), ('depth', 'Depth')]:
        if meta.get(key):
            meta_parts.append(f"{label}: {meta[key]}")
    meta_line = '  |  '.join(meta_parts)

    summary_rows = ''
    for fam in sorted(summary):
        s     = summary[fam]
        color = FAMILY_COLORS.get(fam, '#555')
        summary_rows += (
            f'<tr>'
            f'<td><span class="badge" style="background:{color}">{fam}</span></td>'
            f'<td>{s["count"]}</td>'
            f'<td>frame {s["first_frame"]}</td>'
            f'</tr>'
        )

    cards_data = [
        {
            'cam':    r['cam_id'],
            'family': r['family'],
            'frame':  r['frame_id'],
            'conf':   round(r['confidence'] * 100, 1),
            'file':   r['crop_file'],
            'fkey':   f"{r['cam_id']}_{r['crop_file']}",
            'b64':    r['b64'],
            'x1': r['x1'], 'y1': r['y1'], 'x2': r['x2'], 'y2': r['y2'],
            'fw': r['fw'], 'fh': r['fh'],
        }
        for r in records
    ]

    all_fam_js    = json.dumps(sorted(FAMILY_COLORS.keys()))
    fam_colors_js = json.dumps(FAMILY_COLORS)
    cards_json    = json.dumps(cards_data, ensure_ascii=False)
    cameras_json  = json.dumps(cameras,   ensure_ascii=False)
    fam_opts      = ''.join(f'<option value="{f}">{f}</option>' for f in all_families)
    cam_opts      = ''.join(f'<option value="{c}">{c}</option>' for c in all_cams)

    cam_subtabs = ''.join(
        f'<div class="subtab{" active" if i == 0 else ""}" '
        f'data-cam="{c}" onclick="switchCam(this,\'{c}\')">{c}</div>'
        for i, c in enumerate(all_cams)
    )

    n_detections = len(records)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>RENAI &mdash; {drop_name}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#F5F7FA;color:#1F2933}}

.topbar{{position:sticky;top:0;z-index:100;background:#1A365D;color:#fff;
         padding:12px 24px;display:flex;align-items:center;gap:20px}}
.topbar h1{{font-size:16px;font-weight:700;letter-spacing:.5px}}
.topbar .meta{{font-size:12px;color:#A0C4FF;flex:1}}

.summary{{margin:20px 24px 0;background:#fff;border:1px solid #D9E2EC;border-radius:6px;overflow:hidden}}
.summary h2{{font-size:12px;font-weight:700;color:#52606D;padding:10px 16px;
             background:#F5F7FA;border-bottom:1px solid #D9E2EC;letter-spacing:.5px}}
.summary table{{width:100%;border-collapse:collapse}}
.summary td{{padding:8px 16px;font-size:13px;border-bottom:1px solid #F5F7FA}}
.summary tr:last-child td{{border-bottom:none}}

.tabs{{display:flex;margin:20px 24px 0;border-bottom:2px solid #D9E2EC}}
.tab{{padding:8px 20px;font-size:13px;font-weight:600;cursor:pointer;color:#52606D;
      border:1px solid transparent;border-bottom:none;border-radius:4px 4px 0 0;
      background:#F5F7FA;margin-bottom:-2px}}
.tab.active{{background:#fff;border-color:#D9E2EC;color:#1A365D;border-bottom:2px solid #fff}}

.filters{{background:#fff;border-bottom:1px solid #D9E2EC;
          padding:10px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.filters label{{font-size:12px;color:#52606D;font-weight:600}}
.filters select{{font-size:13px;padding:4px 8px;border:1px solid #D9E2EC;
                 border-radius:4px;background:#fff;cursor:pointer}}
.filters .cnt{{font-size:12px;color:#52606D;margin-left:auto}}
.corr-toggle{{padding:5px 12px;font-size:12px;font-weight:600;
              border:1px solid #D9E2EC;border-radius:4px;background:#F5F7FA;
              cursor:pointer;color:#52606D;transition:all .15s;white-space:nowrap}}
.corr-toggle.active{{background:#1A365D;color:#fff;border-color:#1A365D}}

.gallery{{padding:20px 24px;display:grid;
          grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}}
.card{{background:#fff;border:2px solid #D9E2EC;border-radius:6px;overflow:hidden;
       transition:box-shadow .15s,border-color .15s}}
.card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.12)}}
.card.corrected{{border-color:#48BB78}}
.card img{{width:100%;height:120px;object-fit:cover;display:block;cursor:pointer}}
.card .info{{padding:8px}}
.card .fam{{font-size:11px;font-weight:600;margin-bottom:2px;min-height:22px;
            display:flex;flex-wrap:wrap;align-items:center;gap:3px}}
.card .det{{font-size:10px;color:#52606D}}

.corr-controls{{display:none;padding:6px 8px;background:#F5F7FA;
                border-top:1px solid #D9E2EC}}
.corr-mode .corr-controls{{display:block}}
.corr-sel{{width:100%;font-size:11px;padding:3px 4px;border:1px solid #D9E2EC;
           border-radius:3px;margin-bottom:4px;background:#fff}}
.corr-add-btn{{width:100%;font-size:11px;font-weight:600;padding:4px;
               border:none;border-radius:3px;cursor:pointer;
               background:#1A365D;color:#fff;transition:background .15s}}
.corr-add-btn:hover{{background:#2D3748}}
.corr-add-btn.remove{{background:#E53E3E}}
.corr-add-btn.remove:hover{{background:#C53030}}

.subtabs{{display:flex;gap:4px;padding:16px 24px 0;background:#F5F7FA;
          border-bottom:2px solid #D9E2EC;flex-wrap:wrap}}
.subtab{{padding:6px 16px;font-size:12px;font-weight:600;cursor:pointer;color:#52606D;
         border:1px solid #D9E2EC;border-bottom:none;border-radius:4px 4px 0 0;
         background:#F0F4F8;margin-bottom:-2px}}
.subtab.active{{background:#fff;color:#1A365D;border-bottom:2px solid #fff}}

.frames-list{{padding:20px 24px;display:flex;flex-direction:column;gap:20px}}
.frame-block{{background:#fff;border:1px solid #D9E2EC;border-radius:6px;overflow:hidden}}
.frame-header{{background:#F5F7FA;border-bottom:1px solid #D9E2EC;
               padding:8px 14px;font-size:12px;font-weight:600;color:#52606D;
               display:flex;align-items:center;gap:10px}}
.det-badge{{font-size:10px;padding:2px 7px;border-radius:10px;
            background:#E2E8F0;color:#4A5568;font-weight:600}}
.det-badge.has{{background:#C6F6D5;color:#276749}}
.frame-body{{padding:14px;display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}}
.frame-ann img{{max-width:520px;max-height:340px;width:100%;border-radius:4px;
                border:1px solid #D9E2EC;cursor:pointer;display:block}}
.frame-crops{{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}}
.crop-card{{width:110px;background:#F5F7FA;border:1px solid #D9E2EC;
            border-radius:4px;overflow:hidden;cursor:pointer}}
.crop-card img{{width:100%;height:80px;object-fit:cover;display:block}}
.crop-info{{padding:4px 6px}}
.crop-info .fam{{font-size:10px;font-weight:600}}
.crop-info .conf{{font-size:9px;color:#52606D}}

.badge{{display:inline-block;padding:2px 8px;border-radius:12px;
        color:#fff;font-size:11px;font-weight:600}}
.hidden{{display:none!important}}
.empty{{text-align:center;padding:40px;color:#52606D;font-size:14px;
        grid-column:1/-1}}

#lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.88);
     z-index:200;align-items:center;justify-content:center}}
#lb.on{{display:flex}}
#lb img{{max-width:92vw;max-height:92vh;border-radius:4px}}
#lb .x{{position:absolute;top:20px;right:28px;color:#fff;font-size:32px;
         cursor:pointer;line-height:1}}

.corr-bar{{position:fixed;bottom:0;left:0;right:0;z-index:150;
           background:#1A365D;color:#fff;padding:10px 24px;
           display:flex;align-items:center;gap:16px;flex-wrap:wrap;
           box-shadow:0 -2px 12px rgba(0,0,0,.25)}}
.corr-bar-count{{font-size:13px;font-weight:700;background:#2D4A7A;
                 padding:4px 12px;border-radius:12px;white-space:nowrap}}
.corr-bar-mid{{display:flex;align-items:center;gap:12px;flex:1;flex-wrap:wrap}}
.corr-bar-mid .lbl{{font-size:12px;color:#A0C4FF;font-weight:600}}
.corr-bar-mid label{{font-size:12px;display:flex;align-items:center;gap:5px;cursor:pointer}}
.corr-bar-mid input[type=checkbox]{{cursor:pointer;accent-color:#48BB78}}
.dl-btn{{padding:7px 18px;font-size:13px;font-weight:700;
         border:none;border-radius:5px;background:#48BB78;color:#fff;
         cursor:pointer;white-space:nowrap;transition:background .15s}}
.dl-btn:hover{{background:#38A169}}
.dl-btn:disabled{{background:#4A5568;cursor:not-allowed}}
</style>
</head>
<body>

<div class="topbar">
  <h1>RENAI &mdash; {drop_name}</h1>
  <span class="meta">{meta_line}</span>
</div>

<div class="summary">
  <h2>DETECTION SUMMARY &mdash; {n_detections} detections</h2>
  <table>
    <thead><tr>
      <td style="font-weight:600;font-size:11px;color:#52606D">Family</td>
      <td style="font-weight:600;font-size:11px;color:#52606D">Count</td>
      <td style="font-weight:600;font-size:11px;color:#52606D">First frame</td>
    </tr></thead>
    <tbody>{summary_rows}</tbody>
  </table>
</div>

<div class="tabs">
  <div class="tab active" id="tab-gallery" onclick="switchTab('gallery')">Gallery</div>
  <div class="tab"        id="tab-frames"  onclick="switchTab('frames')">Frames</div>
</div>

<div class="filters" id="filters-gallery">
  <label>Family</label>
  <select id="fF" onchange="filterGallery()">
    <option value="">All families</option>{fam_opts}
  </select>
  <label>Camera</label>
  <select id="fC" onchange="filterGallery()">
    <option value="">All cameras</option>{cam_opts}
  </select>
  <span class="cnt" id="cnt-gallery"></span>
  <button id="corr-mode-btn" class="corr-toggle" onclick="toggleCorrMode()">&#9998; Correction mode</button>
</div>

<div class="gallery" id="view-gallery"></div>

<div class="hidden" id="view-frames">
  <div class="subtabs" id="subtabs">{cam_subtabs}</div>
  <div class="frames-list" id="frames-list"></div>
</div>

<div id="lb" onclick="closeLb()">
  <span class="x">&times;</span>
  <img id="lbImg" src="" alt="">
</div>

<div id="corr-bar" class="corr-bar hidden">
  <span class="corr-bar-count" id="corr-count">0 correction</span>
  <div class="corr-bar-mid">
    <span class="lbl">Include:</span>
    <label><input type="checkbox" id="fmt-png"  checked> PNG</label>
    <label><input type="checkbox" id="fmt-yolo"> YOLO</label>
    <label><input type="checkbox" id="fmt-coco"> COCO JSON</label>
  </div>
  <button class="dl-btn" id="dl-btn" onclick="downloadZip()">Download ZIP &#x25B8;</button>
</div>

<script>
const FC      = {fam_colors_js};
const ALL_FAM = {all_fam_js};
const CARDS   = {cards_json};
const CAMERAS = {cameras_json};

/* ── Main tab switch ── */
function switchTab(t) {{
  document.getElementById('tab-gallery').classList.toggle('active', t === 'gallery');
  document.getElementById('tab-frames').classList.toggle('active',  t === 'frames');
  document.getElementById('filters-gallery').classList.toggle('hidden', t !== 'gallery');
  document.getElementById('view-gallery').classList.toggle('hidden',    t !== 'gallery');
  document.getElementById('view-frames').classList.toggle('hidden',     t !== 'frames');
}}

/* ── Gallery ── */
function _famOpts(current) {{
  return ALL_FAM.map(f =>
    `<option value="${{f}}"${{f === current ? ' selected' : ''}}>${{f}}</option>`
  ).join('');
}}

function buildGallery() {{
  const g = document.getElementById('view-gallery');
  CARDS.forEach((d, idx) => {{
    const card = document.createElement('div');
    card.className   = 'card';
    card.dataset.f   = d.family;
    card.dataset.c   = d.cam;
    card.dataset.idx = idx;

    const col = FC[d.family] || '#555';
    const img = document.createElement('img');
    img.src = `data:image/jpeg;base64,${{d.b64}}`;
    img.alt = d.family;
    img.onerror = () => {{ card.style.display = 'none'; }};
    img.addEventListener('click', e => {{ e.stopPropagation(); openLb(img.src); }});

    const info = document.createElement('div');
    info.className = 'info';
    info.innerHTML =
      `<div class="fam corr-label"><span class="badge" style="background:${{col}}">${{d.family}}</span></div>` +
      `<div class="det">${{d.cam}} &bull; ${{d.frame}} &bull; ${{d.conf}}%</div>`;

    const ctrl = document.createElement('div');
    ctrl.className = 'corr-controls';
    ctrl.innerHTML =
      `<select class="corr-sel">${{_famOpts(d.family)}}</select>` +
      `<button class="corr-add-btn">+ Add</button>`;

    card.appendChild(img);
    card.appendChild(info);
    card.appendChild(ctrl);

    ctrl.querySelector('.corr-add-btn').addEventListener('click', () => _onCorrClick(card, idx));
    g.appendChild(card);
  }});
  filterGallery();
}}

function filterGallery() {{
  const fam = document.getElementById('fF').value;
  const cam = document.getElementById('fC').value;
  let n = 0;
  document.querySelectorAll('#view-gallery .card').forEach(c => {{
    const ok = (!fam || c.dataset.f === fam) && (!cam || c.dataset.c === cam);
    c.classList.toggle('hidden', !ok);
    if (ok) n++;
  }});
  const old = document.querySelector('#view-gallery .empty');
  if (old) old.remove();
  if (!n) {{
    const m = document.createElement('div');
    m.className   = 'empty';
    m.textContent = 'No detections match the current filter.';
    document.getElementById('view-gallery').appendChild(m);
  }}
  document.getElementById('cnt-gallery').textContent = n + ' / ' + CARDS.length + ' detections';
}}

/* ── Correction mode ── */
let corrMode = false;
const corrections = new Map(); // fkey -> corr object

function toggleCorrMode() {{
  corrMode = !corrMode;
  document.getElementById('view-gallery').classList.toggle('corr-mode', corrMode);
  const btn = document.getElementById('corr-mode-btn');
  btn.textContent = corrMode ? '✓ Correction mode (active)' : '✎ Correction mode';
  btn.classList.toggle('active', corrMode);
}}

function _onCorrClick(cardEl, idx) {{
  const d = CARDS[idx];
  if (corrections.has(d.fkey)) {{
    _removeCorr(cardEl, idx);
  }} else {{
    _addCorr(cardEl, idx);
  }}
}}

function _addCorr(cardEl, idx) {{
  const d      = CARDS[idx];
  const newFam = cardEl.querySelector('.corr-sel').value;
  corrections.set(d.fkey, {{
    newFam,
    origFam:  d.family,
    cam:      d.cam,
    frameId:  d.frame,
    conf:     d.conf,
    b64:      d.b64,
    filename: d.file,
    x1: d.x1, y1: d.y1, x2: d.x2, y2: d.y2,
    fw: d.fw,  fh: d.fh,
  }});
  cardEl.classList.add('corrected');
  const oldCol = FC[d.family] || '#555';
  const newCol = FC[newFam]   || '#555';
  cardEl.querySelector('.corr-label').innerHTML =
    `<span class="badge" style="background:${{oldCol}};text-decoration:line-through;opacity:.5">${{d.family}}</span>` +
    `<span style="color:#aaa;font-size:9px"> &#x25B8; </span>` +
    `<span class="badge" style="background:${{newCol}}">${{newFam}}</span>`;
  const btn = cardEl.querySelector('.corr-add-btn');
  btn.textContent = 'Remove';
  btn.classList.add('remove');
  _updateCorrBar();
}}

function _removeCorr(cardEl, idx) {{
  const d = CARDS[idx];
  corrections.delete(d.fkey);
  cardEl.classList.remove('corrected');
  const col = FC[d.family] || '#555';
  cardEl.querySelector('.corr-label').innerHTML =
    `<span class="badge" style="background:${{col}}">${{d.family}}</span>`;
  const btn = cardEl.querySelector('.corr-add-btn');
  btn.textContent = '+ Add';
  btn.classList.remove('remove');
  _updateCorrBar();
}}

function _updateCorrBar() {{
  const n   = corrections.size;
  const bar = document.getElementById('corr-bar');
  bar.classList.toggle('hidden', n === 0);
  document.body.style.paddingBottom = n > 0 ? '72px' : '0';
  document.getElementById('corr-count').textContent =
    n + ' correction' + (n > 1 ? 's' : '');
}}

/* ── ZIP download ── */
async function downloadZip() {{
  if (corrections.size === 0) return;
  if (typeof JSZip === 'undefined') {{
    alert('JSZip not loaded. An internet connection is required to download the ZIP.');
    return;
  }}
  const inclPng  = document.getElementById('fmt-png').checked;
  const inclYolo = document.getElementById('fmt-yolo').checked;
  const inclCoco = document.getElementById('fmt-coco').checked;
  if (!inclPng && !inclYolo && !inclCoco) {{
    alert('Please select at least one output format.');
    return;
  }}

  const dlBtn = document.getElementById('dl-btn');
  dlBtn.disabled = true;
  dlBtn.textContent = 'Generation...';

  const zip  = new JSZip();
  const root = zip.folder('training_corrections');

  const csvRows = ['filename,cam_id,frame_id,renai_label,corrected_label,confidence_pct'];

  const yoloCls = [], yoloClsMap = {{}}, yoloByFrame = {{}};
  let cocoImgId = 1, cocoAnnId = 1, cocoCatId = 1;
  const cocoImages = [], cocoAnns = [], cocoCats = [], cocoCatMap = {{}}, cocoImgMap = {{}};

  corrections.forEach((c) => {{
    if (inclPng) {{
      root.folder(c.newFam).file(c.filename, c.b64, {{base64: true}});
    }}

    csvRows.push(
      `${{c.filename}},${{c.cam}},${{c.frameId}},${{c.origFam}},${{c.newFam}},${{c.conf.toFixed(1)}}%`
    );

    if (inclYolo && c.fw > 0 && c.fh > 0) {{
      if (!(c.newFam in yoloClsMap)) {{
        yoloClsMap[c.newFam] = yoloCls.length;
        yoloCls.push(c.newFam);
      }}
      const cid = yoloClsMap[c.newFam];
      const cx  = ((c.x1 + c.x2) / 2) / c.fw;
      const cy  = ((c.y1 + c.y2) / 2) / c.fh;
      const bw  = (c.x2 - c.x1) / c.fw;
      const bh  = (c.y2 - c.y1) / c.fh;
      const fkey = `${{c.cam}}_${{c.frameId}}`;
      if (!yoloByFrame[fkey]) yoloByFrame[fkey] = [];
      yoloByFrame[fkey].push(`${{cid}} ${{cx.toFixed(6)}} ${{cy.toFixed(6)}} ${{bw.toFixed(6)}} ${{bh.toFixed(6)}}`);
    }}

    if (inclCoco && c.fw > 0 && c.fh > 0) {{
      if (!(c.newFam in cocoCatMap)) {{
        cocoCatMap[c.newFam] = cocoCatId;
        cocoCats.push({{id: cocoCatId, name: c.newFam, supercategory: 'fish'}});
        cocoCatId++;
      }}
      const imgKey = `${{c.cam}}/${{c.frameId}}`;
      if (!(imgKey in cocoImgMap)) {{
        cocoImgMap[imgKey] = cocoImgId;
        cocoImages.push({{id: cocoImgId, file_name: imgKey + '.jpg', width: c.fw, height: c.fh}});
        cocoImgId++;
      }}
      const bw = c.x2 - c.x1, bh = c.y2 - c.y1;
      cocoAnns.push({{
        id:          cocoAnnId++,
        image_id:    cocoImgMap[imgKey],
        category_id: cocoCatMap[c.newFam],
        bbox:        [c.x1, c.y1, bw, bh],
        area:        bw * bh,
        iscrowd:     0,
      }});
    }}
  }});

  if (inclYolo) {{
    const yDir = root.folder('yolo');
    yDir.file('classes.txt', yoloCls.join('\\n'));
    Object.entries(yoloByFrame).forEach(([k, lines]) => {{
      yDir.file(k + '.txt', lines.join('\\n'));
    }});
  }}

  if (inclCoco) {{
    root.file('coco_corrections.json', JSON.stringify({{
      info:        {{description: 'RENAI corrections', version: '1.0'}},
      categories:  cocoCats,
      images:      cocoImages,
      annotations: cocoAnns,
    }}, null, 2));
  }}

  root.file('corrections_log.csv', csvRows.join('\\n'));

  try {{
    const blob = await zip.generateAsync({{type: 'blob', compression: 'DEFLATE'}});
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'training_corrections.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }} catch (e) {{
    alert('Error generating ZIP: ' + e.message);
  }}

  dlBtn.disabled = false;
  dlBtn.textContent = 'Download ZIP ▸';
}}

/* ── Frames -- camera sub-tabs ── */
let currentCam = null;

function buildFrames(camId) {{
  const list = document.getElementById('frames-list');
  list.innerHTML = '';
  const camData = CAMERAS[camId];
  if (!camData) return;

  camData.frames.forEach(fr => {{
    const hasCrops  = fr.crops && fr.crops.length > 0;
    const block     = document.createElement('div');
    block.className = 'frame-block';

    const badgeClass = hasCrops ? 'det-badge has' : 'det-badge';
    const badgeText  = hasCrops
      ? fr.crops.length + ' detection' + (fr.crops.length > 1 ? 's' : '')
      : 'no detection';

    const cropsHtml = hasCrops ? fr.crops.map(cr => {{
      const col = FC[cr.family] || '#555';
      return `<div class="crop-card">
        <img src="${{cr.src}}" alt="${{cr.family}}"
             onerror="this.parentElement.style.display='none'"
             onclick="openLb('${{cr.src}}')">
        <div class="crop-info">
          <div class="fam" style="color:${{col}}">${{cr.family}}</div>
          <div class="conf">${{cr.conf}}%</div>
        </div>
      </div>`;
    }}).join('') : '';

    block.innerHTML = `
      <div class="frame-header">
        ${{fr.frame_id}}
        <span class="${{badgeClass}}">${{badgeText}}</span>
      </div>
      <div class="frame-body">
        <div class="frame-ann">
          <img src="${{fr.img_src}}" alt="${{fr.frame_id}}"
               onerror="this.style.opacity=0.3"
               onclick="openLb('${{fr.img_src}}')">
        </div>
        ${{hasCrops ? '<div class="frame-crops">' + cropsHtml + '</div>' : ''}}
      </div>`;
    list.appendChild(block);
  }});
}}

function switchCam(el, camId) {{
  document.querySelectorAll('.subtab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  currentCam = camId;
  buildFrames(camId);
}}

/* ── Lightbox ── */
function openLb(src) {{
  document.getElementById('lbImg').src = src;
  document.getElementById('lb').classList.add('on');
}}
function closeLb() {{
  document.getElementById('lb').classList.remove('on');
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLb(); }});

/* ── Init ── */
buildGallery();
const firstCam = Object.keys(CAMERAS)[0];
if (firstCam) {{ currentCam = firstCam; buildFrames(firstCam); }}
</script>
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--drop_results', required=True)
    parser.add_argument('--drop_name',    required=True)
    args = parser.parse_args()

    print(f"[HTML] Scanning {args.drop_results}")
    cameras = _scan_cameras(args.drop_results)
    records = _scan_detections_for_gallery(args.drop_results)

    if not cameras:
        print("[HTML] No frames found -- skipping.")
        return

    summary  = _compute_summary(records)
    html_str = _build_html(args.drop_name, records, summary, cameras, args.drop_results)

    out_path = os.path.join(args.drop_results, 'report.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_str)

    n_frames = sum(len(v['frames']) for v in cameras.values())
    print(f"[HTML] {n_frames} frames, {len(records)} detections -- report saved: {out_path}")


if __name__ == '__main__':
    main()
