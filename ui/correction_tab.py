"""
RENAI — Onglet de correction manuelle
Thème sombre, zoom/pan, miniatures des détections, sélection canvas↔panneau.
"""

import json
import math
import os
import re
import sys
import glob
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pandas as pd
from PIL import Image, ImageTk

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core', 'run'))
import correction_state

# ── Palette sombre ─────────────────────────────────────────────────────────────
C_BG          = "#0F1117"
C_CARD        = "#1A1D27"
C_BORDER      = "#252836"
C_TEXT        = "#E2E8F0"
C_TEXT2       = "#7B879A"
C_ACCENT      = "#4299E1"
C_SUCCESS     = "#48BB78"
C_ERROR       = "#FC8181"
C_WARNING     = "#F6AD55"
C_BTN_NEUTRAL = "#2D3748"
C_SELECTED    = "#1E3A5F"
C_CANVAS_BG   = "#070A0E"

F_LABEL = ("Segoe UI", 10)
F_BTN   = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 8)

FAMILIES = [
    'acanthuridae', 'carangidae', 'chaetodontidae', 'haemulidae', 'holocentridae',
    'labridae', 'lutjanidae', 'pomacentridae', 'scaridae', 'scombridae',
    'serranidae', 'sphyraenidae', 'inconnu',
]

FAMILY_COLORS = {
    'acanthuridae':   '#63B3ED',
    'carangidae':     '#E2B96F',
    'chaetodontidae': '#F6AD55',
    'haemulidae':     '#68D391',
    'holocentridae':  '#F687B3',
    'labridae':       '#B794F4',
    'lutjanidae':     '#F6E05E',
    'pomacentridae':  '#4FD1C5',
    'scaridae':       '#E53E3E',
    'scombridae':     '#718096',
    'serranidae':     '#90CDF4',
    'sphyraenidae':   '#ED8936',
    'inconnu':        '#A0AEC0',
}

def _load_species_config():
    cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'config', 'species_config.json')
    by_fam, disp_to_sci = {}, {}
    try:
        with open(cfg, encoding='utf-8') as f:
            data = json.load(f)
        for e in data:
            fam = e.get('family', '').lower()
            sci = e.get('scientific_name', '').strip()
            cn  = e.get('common_name', '').strip()
            if fam and sci:
                disp = f"{cn} ({sci})"
                by_fam.setdefault(fam, []).append(disp)
                disp_to_sci[disp] = sci
    except Exception:
        pass
    return by_fam, disp_to_sci

SPECIES_BY_FAMILY, SPECIES_DISP_TO_SCI = _load_species_config()
_SCI_TO_DISP           = {v: k for k, v in SPECIES_DISP_TO_SCI.items()}
_SPECIES_SCI_TO_FAMILY = {
    SPECIES_DISP_TO_SCI[disp]: fam
    for fam, disps in SPECIES_BY_FAMILY.items()
    for disp in disps
}
_ALL_SPECIES_DISP = [
    disp
    for fam in sorted(SPECIES_BY_FAMILY)
    for disp in SPECIES_BY_FAMILY[fam]
]

_RE_DET_FILE = re.compile(
    r'^(frame_\d+)_(\d+)_(\d+)_(\d+)_(\d+)\.jpg$', re.IGNORECASE
)

METADATA_FIELDS = [
    ('drop_id',    'Drop ID'),
    ('campaign',   'Campaign'),
    ('location',   'Location'),
    ('site',       'Site'),
    ('date',       'Date'),
    ('latitude',   'Latitude'),
    ('longitude',  'Longitude'),
    ('habitat',    'Habitat'),
    ('visibility', 'Visibility'),
    ('depth',      'Depth'),
]


class CorrectionTab(tk.Frame):

    def __init__(self, parent, results_root, get_default_drop_dir=None, log_fn=None):
        super().__init__(parent, bg=C_BG)
        self.results_root          = results_root
        self._get_default_drop_dir = get_default_drop_dir
        self._log                  = log_fn or (lambda *a, **k: None)

        self._campaign_dir = None
        self._drop_dir     = None
        self._cam_id       = None
        self._drop_var     = tk.StringVar()
        self._cam_var      = tk.StringVar()
        self._frames     = []
        self._frame_idx  = 0
        # Couverture de relecture : ids des frames réellement affichées pour la
        # caméra ouverte. Minorant de l'attention portée, jamais une preuve de
        # relecture — cf. core/run/correction_state.py.
        self._seen_frames  = set()
        self._seen_flushed = 0
        # Vrai pendant qu'une régénération tourne en tâche de fond
        self._busy         = False
        self._undo_stack = []
        self._dirty      = False
        self._tk_img     = None
        self._pil_cache  = None   # (frame_path, PIL.Image) — évite le rechargement disque
        self._card_refs  = []     # refs widgets par card pour mise à jour ciblée

        # Mode dessin
        self._draw_mode    = False
        self._draw_rect_id = None
        self._draw_start   = None

        # Transform rendu (espace image → canvas)
        self._render_scale = 1.0
        self._render_ox    = 0
        self._render_oy    = 0
        self._render_iw    = 0
        self._render_ih    = 0

        # Zoom / pan
        self._zoom      = 1.0
        self._pan_x     = 0
        self._pan_y     = 0
        self._pan_start = None

        # Sélection
        self._selected_det_idx = None

        # Refs GC pour thumbnails + widgets cards
        self._thumb_refs  = []
        self._card_frames = []
        self._side_canvas = None

        self._build_ui()

    # ── Construction UI ─────────────────────────────────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self, bg=C_CARD,
                       highlightbackground=C_BORDER, highlightthickness=1)
        top.pack(fill=tk.X, padx=6, pady=(6, 4))
        top_inner = tk.Frame(top, bg=C_CARD, padx=10, pady=8)
        top_inner.pack(fill=tk.X)

        tk.Button(
            top_inner, text="Open for correction ···", font=F_LABEL,
            bg=C_BTN_NEUTRAL, fg=C_TEXT,
            activebackground=C_BORDER, activeforeground=C_TEXT,
            relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2",
            command=self._open_for_correction,
        ).pack(side=tk.LEFT)

        self._lbl_drop_path = tk.Label(
            top_inner, text="No folder selected",
            font=F_LABEL, bg=C_CARD, fg=C_TEXT2,
        )
        self._lbl_drop_path.pack(side=tk.LEFT, padx=(12, 0))

        self._cam_frame = tk.Frame(top_inner, bg=C_CARD)
        self._cam_frame.pack(side=tk.RIGHT)
        tk.Label(self._cam_frame, text="Camera:", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)
        self._cam_combo = ttk.Combobox(
            self._cam_frame, textvariable=self._cam_var,
            state='readonly', width=12, font=F_LABEL,
        )
        self._cam_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._cam_combo.bind('<<ComboboxSelected>>', self._on_camera_selected)

        # Sélecteur Drop (toujours visible)
        self._drop_frame = tk.Frame(top_inner, bg=C_CARD)
        self._drop_frame.pack(side=tk.RIGHT, padx=(0, 10))
        tk.Label(self._drop_frame, text="Drop:", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)
        self._drop_combo = ttk.Combobox(
            self._drop_frame, textvariable=self._drop_var,
            state='readonly', width=18, font=F_LABEL,
        )
        self._drop_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._drop_combo.bind('<<ComboboxSelected>>', self._on_drop_selected)

        # Tampon de correction — même vocabulaire que l'onglet Indicators des
        # classeurs. Affiché ici pour que la personne qui corrige voie, pendant
        # qu'elle travaille, ce que les sorties diront de son travail.
        self._lbl_correction_state = tk.Label(
            self, text=correction_state.tab_summary(None),
            font=F_SMALL, bg=C_CARD, fg=C_TEXT2, anchor='w',
            padx=10, pady=4,
        )
        self._lbl_correction_state.pack(fill=tk.X, padx=6)

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        canvas_card = tk.Frame(body, bg=C_CANVAS_BG,
                               highlightbackground=C_BORDER, highlightthickness=1)
        canvas_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self._canvas = tk.Canvas(canvas_card, bg=C_CANVAS_BG, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._canvas.bind('<Configure>',        lambda e: self._render_frame())
        self._canvas.bind('<ButtonPress-1>',    self._on_canvas_press)
        self._canvas.bind('<B1-Motion>',        self._on_canvas_drag)
        self._canvas.bind('<ButtonRelease-1>',  self._on_canvas_release)
        self._canvas.bind('<Double-Button-1>',  self._on_canvas_double_click)
        self._canvas.bind('<MouseWheel>',       self._on_canvas_scroll)
        self._canvas.bind('<Button-2>',         self._on_pan_start)
        self._canvas.bind('<B2-Motion>',        self._on_pan_drag)

        side = tk.Frame(body, bg=C_CARD, width=300,
                        highlightbackground=C_BORDER, highlightthickness=1)
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)

        self._lbl_frame_info = tk.Label(
            side, text="—", font=("Segoe UI", 10, "bold"),
            bg=C_CARD, fg=C_TEXT, anchor='w',
        )
        self._lbl_frame_info.pack(fill=tk.X, padx=10, pady=(10, 2))

        # Légende statut
        legend = tk.Frame(side, bg=C_CARD, padx=8, pady=4)
        legend.pack(fill=tk.X)
        for color, label in [
            (C_SUCCESS, "Valid"),
            (C_ERROR,   "False positive"),
        ]:
            tk.Label(legend, text="●", font=F_SMALL,
                     bg=C_CARD, fg=color).pack(side=tk.LEFT)
            tk.Label(legend, text=label + "  ", font=F_SMALL,
                     bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)

        tk.Frame(side, bg=C_BORDER, height=1).pack(fill=tk.X, padx=6, pady=(2, 0))

        # Zone tags familles (mise à jour à chaque frame)
        self._tags_frame = tk.Frame(side, bg=C_CARD, padx=8, pady=5)
        self._tags_frame.pack(fill=tk.X)

        tk.Frame(side, bg=C_BORDER, height=1).pack(fill=tk.X, padx=6, pady=(0, 4))

        list_outer = tk.Frame(side, bg=C_CARD)
        list_outer.pack(fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(list_outer, orient=tk.VERTICAL)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._side_canvas = tk.Canvas(
            list_outer, bg=C_CARD, highlightthickness=0,
            yscrollcommand=vsb.set,
        )
        self._side_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self._side_canvas.yview)

        self._side_list = tk.Frame(self._side_canvas, bg=C_CARD)
        _win = self._side_canvas.create_window((0, 0), window=self._side_list, anchor='nw')
        self._side_list.bind(
            '<Configure>',
            lambda e: self._side_canvas.configure(
                scrollregion=self._side_canvas.bbox('all')
            ),
        )
        self._side_canvas.bind(
            '<Configure>',
            lambda e: self._side_canvas.itemconfig(_win, width=e.width),
        )

        def _on_wheel(e):
            self._side_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        self._side_canvas.bind('<MouseWheel>', _on_wheel)
        self._side_list.bind('<MouseWheel>', _on_wheel)

        bottom = tk.Frame(self, bg=C_BG)
        bottom.pack(fill=tk.X, padx=6, pady=(0, 6))
        kw = dict(font=F_BTN, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=10, pady=6, cursor="hand2")

        tk.Button(bottom, text="↩",         bg=C_BTN_NEUTRAL, command=self._undo,         **kw).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(bottom, text="⏮",         bg=C_BTN_NEUTRAL, command=self._go_prev_det,  **kw).pack(side=tk.LEFT, padx=2)
        tk.Button(bottom, text="← Prev.",    bg=C_BTN_NEUTRAL, command=self._go_prev,      **kw).pack(side=tk.LEFT, padx=2)
        tk.Button(bottom, text="Next →",    bg=C_BTN_NEUTRAL, command=self._go_next,      **kw).pack(side=tk.LEFT, padx=2)
        tk.Button(bottom, text="⏭",         bg=C_BTN_NEUTRAL, command=self._go_next_det,  **kw).pack(side=tk.LEFT, padx=2)

        self._btn_draw = tk.Button(
            bottom, text="✎ Bbox", bg=C_BTN_NEUTRAL,
            command=self._toggle_draw_mode, **kw,
        )
        self._btn_draw.pack(side=tk.LEFT, padx=(10, 2))

        tk.Button(bottom, text="⊙ ×1", bg=C_BTN_NEUTRAL,
                  command=self._reset_zoom, **kw).pack(side=tk.LEFT, padx=2)

        self._btn_save = tk.Button(
            bottom, text="💾 Save", bg=C_BTN_NEUTRAL,
            command=self._save, **kw,
        )
        self._btn_save.pack(side=tk.RIGHT)

        tk.Button(
            bottom, text="✎ Metadata", bg=C_BTN_NEUTRAL,
            command=self._show_metadata_editor, **kw,
        ).pack(side=tk.RIGHT, padx=(0, 4))

        tk.Button(
            bottom, text="📤 Export crops", bg=C_BTN_NEUTRAL,
            command=self._export_crops, **kw,
        ).pack(side=tk.RIGHT, padx=(0, 4))

        self.bind_all('<Control-z>',     self._on_ctrl_z)
        self.bind_all('<Control-Key-0>', self._on_ctrl_0)

    def _on_ctrl_z(self, event=None):
        if self.winfo_ismapped():
            self._undo()

    def _on_ctrl_0(self, event=None):
        if self.winfo_ismapped():
            self._reset_zoom()

    # ── Ouverture ─────────────────────────────────────────────────────────────

    def _open_for_correction(self):
        if self._dirty and not self._confirm_discard():
            return
        initial = self.results_root if os.path.isdir(self.results_root) else PROJECT_ROOT
        if self._get_default_drop_dir:
            d = self._get_default_drop_dir()
            if d and os.path.isdir(d):
                initial = d
        folder = filedialog.askdirectory(
            title="Select a results folder (drop or campaign)",
            initialdir=initial,
        )
        if not folder:
            return

        # Mode drop unique
        cams = self._discover_cameras(folder)
        if cams:
            self._campaign_dir = None
            drop_name = os.path.basename(folder)
            self._drop_dir = folder
            self._lbl_drop_path.config(text=drop_name)
            self._drop_combo.config(values=[drop_name])
            self._drop_var.set(drop_name)
            self._cam_combo.config(values=cams)
            self._cam_var.set(cams[0])
            self._load_camera_frames(cams[0])
            return

        # Mode campagne
        drops = self._discover_drops(folder)
        if not drops:
            messagebox.showwarning(
                "Folder not recognized",
                "No drop or camera found in this folder.",
            )
            return
        self._campaign_dir = folder
        self._lbl_drop_path.config(text=os.path.basename(folder))
        self._drop_combo.config(values=drops)
        self._drop_var.set(drops[0])
        self._load_drop(drops[0])

    def _discover_drops(self, folder):
        drops = []
        try:
            for entry in sorted(os.listdir(folder)):
                sub = os.path.join(folder, entry)
                if os.path.isdir(sub) and self._discover_cameras(sub):
                    drops.append(entry)
        except OSError:
            pass
        return drops

    def _load_drop(self, drop_name):
        self._flush_coverage(force=True)   # drop précédent, avant bascule
        self._drop_dir = os.path.join(self._campaign_dir, drop_name)
        cams = self._discover_cameras(self._drop_dir)
        if not cams:
            return
        self._cam_combo.config(values=cams)
        self._cam_var.set(cams[0])
        self._load_camera_frames(cams[0])

    def _on_drop_selected(self, event=None):
        drop = self._drop_var.get()
        current = os.path.basename(self._drop_dir) if self._drop_dir else None
        if drop == current:
            return
        if self._dirty and not self._confirm_discard():
            self._drop_var.set(current)
            return
        if self._campaign_dir:
            target_dir = os.path.join(self._campaign_dir, drop)
            if not self._show_drop_metadata_confirm(drop, target_dir):
                self._drop_var.set(current or drop)
                return
        self._load_drop(drop)

    def _discover_cameras(self, folder):
        # Une seule définition de « ce qu'est une caméra d'un drop », partagée
        # avec l'onglet Habitats et avec le module d'état de correction — elle
        # existait en trois exemplaires identiques.
        return correction_state.camera_ids(folder)

    def _on_camera_selected(self, event=None):
        cam = self._cam_var.get()
        if cam == self._cam_id:
            return
        if self._dirty and not self._confirm_discard():
            self._cam_var.set(self._cam_id)
            return
        self._load_camera_frames(cam)

    def _confirm_discard(self):
        return messagebox.askyesno(
            "Unsaved changes",
            "Unsaved corrections will be lost. Continue?",
        )

    # ── Chargement ────────────────────────────────────────────────────────────

    def _load_camera_frames(self, cam_id):
        self._flush_coverage(force=True)   # caméra précédente, avant bascule
        self._cam_id  = cam_id
        frame_dir     = os.path.join(self._drop_dir, f'{cam_id}_frames')
        det_dir       = os.path.join(self._drop_dir, f'{cam_id}_detections')
        cls_dir       = os.path.join(self._drop_dir, f'{cam_id}_classifications')

        # Read cam CSV once to restore genus/species saved in a previous session
        _restore_gs = {}  # (frame_num, family, n) -> (genus, species)
        _cam_csv    = os.path.join(self._drop_dir, 'csv', f'{cam_id}_classification.csv')
        if os.path.isfile(_cam_csv):
            try:
                _df = pd.read_csv(_cam_csv)
                if 'genus' in _df.columns or 'species' in _df.columns:
                    _cnt: dict = {}
                    for _, _r in _df.iterrows():
                        _fn  = int(_r.get('frame', 0))
                        _fam = str(_r.get('family', ''))
                        _k   = (_fn, _fam)
                        _n   = _cnt.get(_k, 0)
                        _cnt[_k] = _n + 1
                        _g = _r.get('genus',   '')
                        _s = _r.get('species', '')
                        _restore_gs[(_fn, _fam, _n)] = (
                            '' if pd.isna(_g) else str(_g),
                            '' if pd.isna(_s) else str(_s),
                        )
            except Exception:
                pass

        frames = []
        for fp in sorted(glob.glob(os.path.join(frame_dir, '*.jpg'))):
            frame_id  = os.path.splitext(os.path.basename(fp))[0]
            m         = re.search(r'frame_(\d+)', frame_id)
            frame_num = int(m.group(1)) if m else 0

            detections  = []
            _fam_cnt: dict = {}
            for det_path in sorted(glob.glob(os.path.join(det_dir, f'{frame_id}_*.jpg'))):
                det_name = os.path.basename(det_path)
                dm = _RE_DET_FILE.match(det_name)
                if not dm:
                    continue
                x1, y1, x2, y2 = (int(dm.group(i)) for i in (2, 3, 4, 5))
                det_id   = os.path.splitext(det_name)[0]
                cls_path = os.path.join(cls_dir, frame_id, f'{det_id}.txt')

                family, confidence, status = 'inconnu', 0.0, 'ok'
                if os.path.isfile(cls_path):
                    try:
                        with open(cls_path, encoding='utf-8') as f:
                            first_line = f.readline()
                        parts      = first_line.split(':')
                        raw_fam    = parts[0].strip()
                        confidence = float(parts[1].strip())
                        if raw_fam == 'fp':
                            status = 'fp'
                        else:
                            family = raw_fam
                    except Exception:
                        pass

                _fk     = (frame_num, family)
                _fn_idx = _fam_cnt.get(_fk, 0)
                _fam_cnt[_fk] = _fn_idx + 1
                _genus, _species = _restore_gs.get((frame_num, family, _fn_idx), ('', ''))

                detections.append({
                    'bbox':        [x1, y1, x2, y2],
                    'family':      family,
                    'family_orig': family,
                    'confidence':  confidence,
                    'status':      status,
                    'det_file':    det_name,
                    'genus':       _genus,
                    'species':     _species,
                })

            frames.append({
                'frame_id':   frame_id,
                'frame_num':  frame_num,
                'frame_path': fp,
                'detections': detections,
            })

        # Rechargement des détections ajoutées manuellement (sidecar JSON)
        _manual_path = os.path.join(self._drop_dir, 'csv', f'{cam_id}_manual_detections.json')
        if os.path.isfile(_manual_path):
            try:
                with open(_manual_path, encoding='utf-8') as _mf:
                    _manual_data = json.load(_mf)
                for _fr in frames:
                    for _md in _manual_data.get(str(_fr['frame_num']), []):
                        _fr['detections'].append({
                            'bbox':        _md['bbox'],
                            'family':      _md['family'],
                            'family_orig': _md.get('family_orig', _md['family']),
                            'genus':       _md.get('genus', ''),
                            'species':     _md.get('species', ''),
                            'confidence':  float(_md.get('confidence', 1.0)),
                            'status':      _md.get('status', 'added'),
                            'det_file':    None,
                        })
            except Exception as _e:
                self._log(f"[WARN] Manual detections sidecar unreadable: {_e}\n", "error")

        self._frames           = frames
        self._frame_idx        = 0
        self._seen_frames      = set()
        self._seen_flushed     = 0
        self._undo_stack.clear()
        self._dirty            = False
        self._selected_det_idx = None
        self._reset_zoom(render=False)
        if self._draw_mode:
            self._toggle_draw_mode()
        self._update_save_btn()
        self._render_frame()
        self._log(f"[INFO] Correction — {len(frames)} frame(s) loaded for {cam_id}\n", "info")

    # ── Rendu canvas ──────────────────────────────────────────────────────────

    def _det_color(self, det):
        if det['status'] == 'fp':
            return C_ERROR
        if det['family'] != det['family_orig']:
            return C_SUCCESS
        return FAMILY_COLORS.get(det['family'], C_TEXT2)

    def _render_frame(self):
        if not self._frames:
            self._canvas.delete('all')
            self._lbl_frame_info.config(text="—")
            for w in self._side_list.winfo_children():
                w.destroy()
            return

        fr = self._frames[self._frame_idx]
        self._lbl_frame_info.config(
            text=f"Frame {self._frame_idx + 1}/{len(self._frames)} — {fr['frame_id']}"
        )
        self._seen_frames.add(fr['frame_id'])
        self._flush_coverage()
        self._update_correction_state_label()

        try:
            if self._pil_cache and self._pil_cache[0] == fr['frame_path']:
                img = self._pil_cache[1]
            else:
                img = Image.open(fr['frame_path']).convert('RGB')
                self._pil_cache = (fr['frame_path'], img)
        except Exception as e:
            self._canvas.delete('all')
            self._canvas.create_text(10, 10, anchor='nw', fill=C_ERROR,
                                     text=f"Error: {e}")
            return

        iw, ih = img.size
        self._canvas.update_idletasks()
        cw = max(self._canvas.winfo_width(), 200)
        ch = max(self._canvas.winfo_height(), 200)

        base_scale = min(cw / iw, ch / ih)
        scale      = base_scale * self._zoom
        dw         = max(int(iw * scale), 1)
        dh         = max(int(ih * scale), 1)
        ox         = (cw - dw) // 2 + self._pan_x
        oy         = (ch - dh) // 2 + self._pan_y

        # Crop uniquement la région visible (efficacité au zoom élevé)
        vis_x1 = max(0, math.floor(-ox / scale))
        vis_y1 = max(0, math.floor(-oy / scale))
        vis_x2 = min(iw, math.ceil((cw - ox) / scale) + 1)
        vis_y2 = min(ih, math.ceil((ch - oy) / scale) + 1)

        self._canvas.delete('all')

        if vis_x2 > vis_x1 and vis_y2 > vis_y1:
            crop   = img.crop((vis_x1, vis_y1, vis_x2, vis_y2))
            crop_w = max(int((vis_x2 - vis_x1) * scale), 1)
            crop_h = max(int((vis_y2 - vis_y1) * scale), 1)
            disp   = crop.resize((crop_w, crop_h), Image.LANCZOS)
            self._tk_img = ImageTk.PhotoImage(disp)
            self._canvas.create_image(
                ox + int(vis_x1 * scale),
                oy + int(vis_y1 * scale),
                image=self._tk_img, anchor='nw',
            )

        self._render_scale = scale
        self._render_ox    = ox
        self._render_oy    = oy
        self._render_iw    = iw
        self._render_ih    = ih

        for i, det in enumerate(fr['detections']):
            x1, y1, x2, y2 = det['bbox']
            rx1 = ox + x1 * scale
            ry1 = oy + y1 * scale
            rx2 = ox + x2 * scale
            ry2 = oy + y2 * scale
            color = self._det_color(det)
            dash  = (4, 2) if det['status'] == 'added' else None
            width = 3 if i == self._selected_det_idx else 2
            self._canvas.create_rectangle(
                rx1, ry1, rx2, ry2, outline=color, width=width, dash=dash,
                tags='bbox',
            )
            label = f"{i + 1}. {det['family']}"
            if det['status'] == 'fp':
                label += "  [FP]"
            elif det['status'] == 'added':
                label += "  [added]"
            self._canvas.create_text(
                rx1 + 3, max(ry1 - 10, 2),
                text=label, fill=color, anchor='w', font=F_SMALL, tags='bbox',
            )

        self._render_side_panel(fr)

    # ── Panneau latéral ───────────────────────────────────────────────────────

    def _render_side_panel(self, fr):
        try:
            _scroll_pos = self._side_canvas.yview()[0]
        except Exception:
            _scroll_pos = 0.0

        self._thumb_refs  = []
        self._card_frames = []
        self._card_refs   = []
        for w in self._side_list.winfo_children():
            w.destroy()

        # Tags familles présentes sur la frame
        for w in self._tags_frame.winfo_children():
            w.destroy()
        families_present = sorted({
            det['family'] for det in fr['detections']
            if det['status'] != 'fp'
        })
        if families_present:
            for fam in families_present:
                color = FAMILY_COLORS.get(fam, C_TEXT2)
                tk.Label(
                    self._tags_frame, text=fam, font=F_SMALL,
                    bg=color, fg=C_BG, padx=6, pady=2,
                ).pack(side=tk.LEFT, padx=(0, 4))
        else:
            tk.Label(self._tags_frame, text="—", font=F_SMALL,
                     bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)

        if not fr['detections']:
            tk.Label(
                self._side_list, text="No detection on this frame.",
                font=F_LABEL, bg=C_CARD, fg=C_TEXT2, wraplength=260,
            ).pack(anchor='w', padx=10, pady=10)
            return

        for i, det in enumerate(fr['detections']):
            self._build_detection_card(i, det)

        # Restaurer la position de scroll après rebuild
        self._side_list.update_idletasks()
        if self._selected_det_idx is not None:
            self._scroll_to_card(self._selected_det_idx)
        else:
            self._side_canvas.yview_moveto(_scroll_pos)

        # Propager la molette à tous les widgets enfants du panneau
        self._bind_side_scroll(self._side_list)

    def _bind_side_scroll(self, widget):
        if not isinstance(widget, ttk.Combobox):
            def _scroll(e):
                self._side_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
                return 'break'
            widget.bind('<MouseWheel>', _scroll)
        for child in widget.winfo_children():
            self._bind_side_scroll(child)

    def _build_detection_card(self, idx, det):
        x1, y1, x2, y2 = det['bbox']
        w_px, h_px      = x2 - x1, y2 - y1
        is_fp           = det['status'] == 'fp'
        is_unknown      = det['family'] == 'inconnu'
        is_added        = det['status'] == 'added'
        is_selected     = (idx == self._selected_det_idx)
        family_changed  = det['family'] != det['family_orig']

        card_bg = C_SELECTED if is_selected else C_CARD

        if is_fp:
            bar_color = C_ERROR
        else:
            bar_color = FAMILY_COLORS.get(det['family'], C_BORDER)

        wrapper = tk.Frame(
            self._side_list, bg=bar_color,
            highlightbackground=C_ACCENT if is_selected else C_BORDER,
            highlightthickness=1,
        )
        wrapper.pack(fill=tk.X, padx=4, pady=3)
        self._card_frames.append(wrapper)

        bar_frame = tk.Frame(wrapper, bg=bar_color, width=4)
        bar_frame.pack(side=tk.LEFT, fill=tk.Y)

        inner = tk.Frame(wrapper, bg=card_bg, padx=8, pady=6)
        inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # En-tête : numéro + famille (bold) | badge taille
        header = tk.Frame(inner, bg=card_bg)
        header.pack(fill=tk.X)
        title_text = f"{idx + 1}. {det['family']}"
        if is_added:
            title_text += "  [added]"
        title_lbl = tk.Label(
            header, text=title_text,
            font=("Segoe UI", 10, "bold"),
            bg=card_bg, fg=C_TEXT2 if is_fp else C_TEXT,
        )
        title_lbl.pack(side=tk.LEFT)
        size_fg = C_SUCCESS if (w_px >= 64 and h_px >= 64) else C_TEXT2
        tk.Label(
            header, text=f"{w_px}×{h_px} px",
            font=F_SMALL, bg=C_BTN_NEUTRAL, fg=size_fg, padx=5, pady=1,
        ).pack(side=tk.RIGHT)

        # Dropdown famille
        row = tk.Frame(inner, bg=card_bg)
        row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(row, text="Family:", font=F_SMALL,
                 bg=card_bg, fg=C_TEXT2).pack(side=tk.LEFT)
        fam_var = tk.StringVar(value=det['family'])
        fam_cb = ttk.Combobox(
            row, textvariable=fam_var, values=FAMILIES,
            state='readonly', width=14, font=F_SMALL,
        )
        fam_cb.pack(side=tk.LEFT, padx=(4, 0))
        fam_cb.bind(
            '<<ComboboxSelected>>',
            lambda e, d=det, v=fam_var: self._on_family_change(d, v.get()),
        )

        # Dropdown espèce : filtré par famille si connue, sinon toutes les espèces
        row2 = tk.Frame(inner, bg=card_bg)
        row2.pack(fill=tk.X, pady=(4, 0))
        tk.Label(row2, text="Species:", font=F_SMALL,
                 bg=card_bg, fg=C_TEXT2).pack(side=tk.LEFT)
        cur_sci  = det.get('species', '')
        cur_disp = _SCI_TO_DISP.get(cur_sci, '')
        _fam     = det['family']
        if _fam == 'inconnu':
            sp_options = _ALL_SPECIES_DISP
            sp_state   = 'readonly'
        else:
            sp_options = SPECIES_BY_FAMILY.get(_fam, [])
            sp_state   = 'readonly' if sp_options else 'disabled'
        sp_var = tk.StringVar(value=cur_disp)
        sp_cb  = ttk.Combobox(
            row2, textvariable=sp_var, values=sp_options,
            state=sp_state, width=22, font=F_SMALL,
        )
        sp_cb.pack(side=tk.LEFT, padx=(4, 0))
        sp_cb.bind(
            '<<ComboboxSelected>>',
            lambda e, d=det, v=sp_var: self._on_species_change(d, v.get()),
        )

        # Boutons statut
        btn_row = tk.Frame(inner, bg=card_bg)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        tk.Button(
            btn_row, text="✓ Valid", font=F_SMALL,
            bg=C_SUCCESS if not is_fp else C_BTN_NEUTRAL,
            fg=C_BG if not is_fp else C_TEXT2,
            relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
            command=lambda d=det: self._set_status(d, 'ok'),
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            btn_row, text="✗ False positive", font=F_SMALL,
            bg=C_ERROR if is_fp else C_BTN_NEUTRAL,
            fg=C_BG if is_fp else C_TEXT2,
            relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
            command=lambda d=det: self._set_status(d, 'fp'),
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            btn_row, text="? Unknown", font=F_SMALL,
            bg=FAMILY_COLORS['inconnu'] if is_unknown else C_BTN_NEUTRAL,
            fg=C_BG if is_unknown else C_TEXT2,
            relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
            command=lambda d=det: self._on_family_change(d, 'inconnu'),
        ).pack(side=tk.LEFT)

        self._card_refs.append({
            'wrapper':   wrapper,
            'bar_frame': bar_frame,
            'inner':     inner,
            'title_lbl': title_lbl,
            'fam_var':   fam_var,
            'sp_var':    sp_var,
            'sp_cb':     sp_cb,
        })

    # ── Sélection canvas ↔ panneau ────────────────────────────────────────────

    def _on_canvas_click_select(self, event):
        fr     = self._frames[self._frame_idx]
        scale  = self._render_scale
        ox, oy = self._render_ox, self._render_oy

        best_idx  = None
        best_area = float('inf')
        for i, det in enumerate(fr['detections']):
            x1, y1, x2, y2 = det['bbox']
            rx1 = ox + x1 * scale
            ry1 = oy + y1 * scale
            rx2 = ox + x2 * scale
            ry2 = oy + y2 * scale
            if rx1 <= event.x <= rx2 and ry1 <= event.y <= ry2:
                area = (x2 - x1) * (y2 - y1)
                if area < best_area:
                    best_area = area
                    best_idx  = i

        if best_idx == self._selected_det_idx:
            return
        self._selected_det_idx = best_idx
        self._render_frame()
        if best_idx is not None:
            self._scroll_to_card(best_idx)

    def _scroll_to_card(self, idx):
        if self._side_canvas is None or not self._card_frames or idx >= len(self._card_frames):
            return
        self._side_canvas.update_idletasks()
        total_h  = self._side_list.winfo_height()
        canvas_h = self._side_canvas.winfo_height()
        if total_h <= canvas_h or total_h <= 0:
            return
        card   = self._card_frames[idx]
        card_y = card.winfo_y()
        card_h = card.winfo_height()
        target = (card_y + card_h / 2 - canvas_h / 2) / total_h
        self._side_canvas.yview_moveto(max(0.0, min(target, 1.0)))

    # ── Zoom / pan ────────────────────────────────────────────────────────────

    def _on_canvas_scroll(self, event):
        if not self._frames or self._render_iw <= 0:
            return
        factor   = 1.15 if event.delta > 0 else 1 / 1.15
        new_zoom = max(0.5, min(self._zoom * factor, 6.0))
        if new_zoom == self._zoom:
            return

        old_scale = self._render_scale
        new_scale = old_scale * (new_zoom / self._zoom)

        if old_scale > 0:
            img_x = (event.x - self._render_ox) / old_scale
            img_y = (event.y - self._render_oy) / old_scale
        else:
            img_x = img_y = 0.0

        self._zoom = new_zoom

        cw  = self._canvas.winfo_width()
        ch  = self._canvas.winfo_height()
        iw  = self._render_iw
        ih  = self._render_ih
        dw  = int(iw * new_scale)
        dh  = int(ih * new_scale)
        self._pan_x = int(event.x - img_x * new_scale - (cw - dw) // 2)
        self._pan_y = int(event.y - img_y * new_scale - (ch - dh) // 2)

        self._render_frame()

    def _on_pan_start(self, event):
        self._pan_start = (event.x, event.y, self._pan_x, self._pan_y)

    def _on_pan_drag(self, event):
        if self._pan_start is None:
            return
        x0, y0, px0, py0 = self._pan_start
        self._pan_x = px0 + event.x - x0
        self._pan_y = py0 + event.y - y0
        self._render_frame()

    def _reset_zoom(self, render=True):
        self._zoom  = 1.0
        self._pan_x = 0
        self._pan_y = 0
        if render:
            self._render_frame()

    # ── Édition / undo ────────────────────────────────────────────────────────

    def _push_undo_edit(self, det):
        try:
            idx = self._frames[self._frame_idx]['detections'].index(det)
        except ValueError:
            return
        self._undo_stack.append(('edit', self._frame_idx, idx, dict(det)))

    def _push_undo_add(self, frame_idx, det_idx):
        self._undo_stack.append(('add', frame_idx, det_idx, None))

    def _redraw_bboxes(self):
        self._canvas.delete('bbox')
        if not self._frames or self._render_scale <= 0:
            return
        fr    = self._frames[self._frame_idx]
        scale = self._render_scale
        ox    = self._render_ox
        oy    = self._render_oy
        for i, det in enumerate(fr['detections']):
            x1, y1, x2, y2 = det['bbox']
            rx1 = ox + x1 * scale
            ry1 = oy + y1 * scale
            rx2 = ox + x2 * scale
            ry2 = oy + y2 * scale
            color = self._det_color(det)
            dash  = (4, 2) if det['status'] == 'added' else None
            width = 3 if i == self._selected_det_idx else 2
            self._canvas.create_rectangle(
                rx1, ry1, rx2, ry2, outline=color, width=width,
                dash=dash, tags='bbox',
            )
            label = f"{i + 1}. {det['family']}"
            if det['status'] == 'fp':
                label += "  [FP]"
            elif det['status'] == 'added':
                label += "  [added]"
            self._canvas.create_text(
                rx1 + 3, max(ry1 - 10, 2),
                text=label, fill=color, anchor='w', font=F_SMALL, tags='bbox',
            )

    def _update_family_tags(self):
        if not self._frames:
            return
        fr = self._frames[self._frame_idx]
        for w in self._tags_frame.winfo_children():
            w.destroy()
        families_present = sorted({
            det['family'] for det in fr['detections']
            if det['status'] != 'fp' and det['family'] != 'inconnu'
        })
        if families_present:
            for fam in families_present:
                color = FAMILY_COLORS.get(fam, C_TEXT2)
                tk.Label(
                    self._tags_frame, text=fam, font=F_SMALL,
                    bg=color, fg=C_BG, padx=6, pady=2,
                ).pack(side=tk.LEFT, padx=(0, 4))
        else:
            tk.Label(self._tags_frame, text="—", font=F_SMALL,
                     bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)

    def _update_card(self, idx):
        if idx >= len(self._card_refs):
            return
        fr  = self._frames[self._frame_idx]
        det = fr['detections'][idx]
        ref = self._card_refs[idx]

        is_fp      = det['status'] == 'fp'
        is_added   = det['status'] == 'added'
        is_selected = idx == self._selected_det_idx
        card_bg    = C_SELECTED if is_selected else C_CARD
        bar_color  = C_ERROR if is_fp else FAMILY_COLORS.get(det['family'], C_BORDER)

        ref['wrapper'].config(bg=bar_color)
        ref['bar_frame'].config(bg=bar_color)
        ref['inner'].config(bg=card_bg)

        title_text = f"{idx + 1}. {det['family']}"
        if is_added:
            title_text += "  [added]"
        ref['title_lbl'].config(text=title_text, bg=card_bg,
                                fg=C_TEXT2 if is_fp else C_TEXT)

        ref['fam_var'].set(det['family'])

        _fam = det['family']
        if _fam == 'inconnu':
            sp_options = _ALL_SPECIES_DISP
            sp_state   = 'readonly'
        else:
            sp_options = SPECIES_BY_FAMILY.get(_fam, [])
            sp_state   = 'readonly' if sp_options else 'disabled'
        ref['sp_var'].set(_SCI_TO_DISP.get(det.get('species', ''), ''))
        ref['sp_cb'].config(values=sp_options, state=sp_state)

    def _on_family_change(self, det, new_family):
        if new_family == det['family']:
            return
        self._push_undo_edit(det)
        det['family']  = new_family
        det['genus']   = ''
        det['species'] = ''
        self._mark_dirty()
        fr  = self._frames[self._frame_idx]
        try:
            idx = fr['detections'].index(det)
        except ValueError:
            self._redraw_bboxes(); self._update_family_tags(); return
        self._redraw_bboxes()
        self._update_card(idx)
        self._update_family_tags()

    def _on_species_change(self, det, disp_value):
        sci    = SPECIES_DISP_TO_SCI.get(disp_value, '')
        genus  = sci.split(' ')[0] if sci else ''
        family = _SPECIES_SCI_TO_FAMILY.get(sci, det['family'])
        if det.get('species') == sci and det.get('family') == family:
            return
        self._push_undo_edit(det)
        det['species'] = sci
        det['genus']   = genus
        det['family']  = family
        self._mark_dirty()
        fr  = self._frames[self._frame_idx]
        try:
            idx = fr['detections'].index(det)
        except ValueError:
            self._redraw_bboxes(); self._update_family_tags(); return
        self._redraw_bboxes()
        self._update_card(idx)
        self._update_family_tags()

    def _set_status(self, det, status):
        if det['status'] == status:
            return
        self._push_undo_edit(det)
        det['status'] = status
        self._mark_dirty()
        self._render_frame()

    def _undo(self):
        if not self._undo_stack:
            return
        kind, frame_idx, det_idx, payload = self._undo_stack.pop()
        self._frame_idx = frame_idx
        dets = self._frames[frame_idx]['detections']
        if kind == 'edit':
            dets[det_idx] = payload
        elif kind == 'add':
            if 0 <= det_idx < len(dets):
                del dets[det_idx]
                if self._selected_det_idx == det_idx:
                    self._selected_det_idx = None
        self._dirty = bool(self._undo_stack)
        self._update_save_btn()
        self._render_frame()

    def _mark_dirty(self):
        self._dirty = True
        self._update_save_btn()

    def _update_save_btn(self):
        self._btn_save.config(bg=C_WARNING if self._dirty else C_BTN_NEUTRAL)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _go_prev(self):
        if self._frame_idx > 0:
            self._frame_idx       -= 1
            self._selected_det_idx = None
            self._render_frame()

    def _go_next(self):
        if self._frame_idx < len(self._frames) - 1:
            self._frame_idx       += 1
            self._selected_det_idx = None
            self._render_frame()

    def _go_prev_det(self):
        for i in range(self._frame_idx - 1, -1, -1):
            if self._frames[i]['detections']:
                self._frame_idx       = i
                self._selected_det_idx = None
                self._render_frame()
                return

    def _go_next_det(self):
        for i in range(self._frame_idx + 1, len(self._frames)):
            if self._frames[i]['detections']:
                self._frame_idx       = i
                self._selected_det_idx = None
                self._render_frame()
                return

    # ── Mode dessin ───────────────────────────────────────────────────────────

    def _toggle_draw_mode(self):
        if not self._frames:
            return
        self._draw_mode = not self._draw_mode
        self._canvas.config(cursor='crosshair' if self._draw_mode else '')
        self._btn_draw.config(bg=C_ACCENT if self._draw_mode else C_BTN_NEUTRAL)
        if self._draw_mode:
            self._selected_det_idx = None
            self._render_frame()

    def _on_canvas_press(self, event):
        if self._draw_mode and self._frames:
            self._draw_start   = (event.x, event.y)
            self._draw_rect_id = self._canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline=C_ACCENT, width=2, dash=(4, 2),
            )
        elif not self._draw_mode and self._frames:
            self._on_canvas_click_select(event)

    def _on_canvas_drag(self, event):
        if not self._draw_mode or self._draw_rect_id is None:
            return
        x0, y0 = self._draw_start
        self._canvas.coords(self._draw_rect_id, x0, y0, event.x, event.y)

    def _on_canvas_release(self, event):
        if not self._draw_mode or self._draw_rect_id is None:
            return
        x0, y0 = self._draw_start
        self._canvas.delete(self._draw_rect_id)
        self._draw_rect_id = None
        self._draw_start   = None

        cx1, cy1 = min(x0, event.x), min(y0, event.y)
        cx2, cy2 = max(x0, event.x), max(y0, event.y)

        scale = self._render_scale
        if scale <= 0:
            return
        ix1 = (cx1 - self._render_ox) / scale
        iy1 = (cy1 - self._render_oy) / scale
        ix2 = (cx2 - self._render_ox) / scale
        iy2 = (cy2 - self._render_oy) / scale

        iw, ih = self._render_iw, self._render_ih
        ix1 = max(0, min(ix1, iw))
        iy1 = max(0, min(iy1, ih))
        ix2 = max(0, min(ix2, iw))
        iy2 = max(0, min(iy2, ih))

        if (ix2 - ix1) < 5 or (iy2 - iy1) < 5:
            return

        family = self._prompt_family()
        if not family:
            return

        fr  = self._frames[self._frame_idx]
        det = {
            'bbox':        [int(ix1), int(iy1), int(ix2), int(iy2)],
            'family':      family,
            'family_orig': family,
            'genus':       '',
            'species':     '',
            'confidence':  1.0,
            'status':      'added',
            'det_file':    None,
        }
        fr['detections'].append(det)
        new_idx = len(fr['detections']) - 1
        self._push_undo_add(self._frame_idx, new_idx)
        self._selected_det_idx = new_idx
        self._mark_dirty()
        self._render_frame()
        self._scroll_to_card(new_idx)

    def _prompt_family(self):
        result = {'value': None}

        dlg = tk.Toplevel(self)
        dlg.title("Family of the new detection")
        dlg.configure(bg=C_CARD)
        dlg.transient(self.winfo_toplevel())
        dlg.resizable(False, False)

        inner = tk.Frame(dlg, bg=C_CARD, padx=16, pady=14)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text="Family:", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT).pack(anchor='w')
        choices = list(FAMILIES)
        fam_var = tk.StringVar(value=choices[0])
        cb = ttk.Combobox(
            inner, textvariable=fam_var, values=choices,
            state='readonly', width=20, font=F_LABEL,
        )
        cb.pack(anchor='w', pady=(4, 12))
        cb.focus_set()

        def _confirm(event=None):
            result['value'] = fam_var.get()
            dlg.destroy()

        def _cancel(event=None):
            dlg.destroy()

        btn_row = tk.Frame(inner, bg=C_CARD)
        btn_row.pack(fill=tk.X)
        tk.Button(btn_row, text="Cancel", font=F_SMALL,
                  bg=C_BTN_NEUTRAL, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=10, pady=4, cursor="hand2", command=_cancel,
                  ).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(btn_row, text="Add", font=F_SMALL,
                  bg=C_ACCENT, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=10, pady=4, cursor="hand2", command=_confirm,
                  ).pack(side=tk.RIGHT)

        dlg.bind('<Return>', _confirm)
        dlg.bind('<Escape>', _cancel)

        dlg.update_idletasks()
        root = self.winfo_toplevel()
        px   = root.winfo_rootx() + (root.winfo_width()  - dlg.winfo_width())  // 2
        py   = root.winfo_rooty() + (root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{max(px, 0)}+{max(py, 0)}")

        dlg.grab_set()
        self.wait_window(dlg)
        return result['value']

    # ── Metadata confirm + editor ─────────────────────────────────────────────

    def _show_drop_metadata_confirm(self, drop_name, drop_dir):
        meta = {}
        meta_path = os.path.join(drop_dir, 'drop_metadata.json')
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                pass

        confirmed = [False]
        dlg = tk.Toplevel(self)
        dlg.title(f"Drop — {drop_name}")
        dlg.resizable(False, False)
        dlg.configure(bg=C_CARD)
        dlg.grab_set()
        dlg.attributes('-topmost', True)

        outer = tk.Frame(dlg, bg=C_CARD, padx=24, pady=20)
        outer.pack(fill=tk.BOTH, expand=True)

        tk.Label(outer, text=drop_name, font=("Segoe UI", 11, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(anchor='w', pady=(0, 14))

        grid = tk.Frame(outer, bg=C_CARD)
        grid.pack(fill=tk.X)

        for i, (key, label) in enumerate(METADATA_FIELDS):
            tk.Label(grid, text=label, font=F_LABEL, bg=C_CARD,
                     fg=C_TEXT2, anchor='w', width=12).grid(
                         row=i, column=0, sticky='w', pady=2)
            val = str(meta.get(key, '') or '—')
            tk.Label(grid, text=val, font=("Segoe UI", 10, "bold"),
                     bg=C_CARD, fg=C_TEXT, anchor='w').grid(
                         row=i, column=1, sticky='w', padx=(8, 0), pady=2)

        tk.Frame(outer, bg=C_BORDER, height=1).pack(fill=tk.X, pady=(16, 14))

        btn_row = tk.Frame(outer, bg=C_CARD)
        btn_row.pack(anchor='e')

        tk.Button(
            btn_row, text="Cancel", font=F_LABEL,
            bg=C_CARD, fg=C_TEXT2,
            activebackground=C_BORDER, activeforeground=C_TEXT,
            relief=tk.FLAT, bd=0, padx=14, pady=5, cursor="hand2",
            highlightbackground=C_BORDER, highlightthickness=1,
            command=dlg.destroy,
        ).pack(side=tk.LEFT, padx=(0, 8))

        def _confirm():
            confirmed[0] = True
            dlg.destroy()

        tk.Button(
            btn_row, text="Load drop", font=("Segoe UI", 10, "bold"),
            bg=C_ACCENT, fg=C_BG,
            activebackground="#2B6CB0", activeforeground=C_BG,
            relief=tk.FLAT, bd=0, padx=20, pady=5, cursor="hand2",
            command=_confirm,
        ).pack(side=tk.LEFT)

        dlg.bind('<Return>', lambda e: _confirm())
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        root = self.winfo_toplevel()
        dlg.update_idletasks()
        x = root.winfo_x() + (root.winfo_width()  - dlg.winfo_width())  // 2
        y = root.winfo_y() + (root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self.wait_window(dlg)
        return confirmed[0]

    def _show_metadata_editor(self):
        if not self._drop_dir:
            messagebox.showwarning("No drop loaded", "Please open a results folder first.")
            return

        meta = {}
        meta_path = os.path.join(self._drop_dir, 'drop_metadata.json')
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                pass

        dlg = tk.Toplevel(self)
        drop_name = os.path.basename(self._drop_dir)
        dlg.title(f"Metadata — {drop_name}")
        dlg.resizable(False, False)
        dlg.configure(bg=C_CARD)
        dlg.grab_set()
        dlg.attributes('-topmost', True)

        outer = tk.Frame(dlg, bg=C_CARD, padx=24, pady=20)
        outer.pack(fill=tk.BOTH, expand=True)

        tk.Label(outer, text=f"Metadata — {drop_name}",
                 font=("Segoe UI", 11, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(anchor='w', pady=(0, 14))

        grid = tk.Frame(outer, bg=C_CARD)
        grid.pack(fill=tk.X)

        entry_vars = {}
        for i, (key, label) in enumerate(METADATA_FIELDS):
            tk.Label(grid, text=label, font=F_LABEL, bg=C_CARD,
                     fg=C_TEXT2, anchor='w', width=12).grid(
                         row=i, column=0, sticky='w', pady=3)
            v = tk.StringVar(value=str(meta.get(key, '') or ''))
            e = tk.Entry(grid, textvariable=v, font=F_LABEL, width=26,
                         bg=C_BG, fg=C_TEXT, insertbackground=C_TEXT,
                         relief=tk.FLAT, bd=0,
                         highlightbackground=C_BORDER, highlightthickness=1)
            e.grid(row=i, column=1, sticky='w', padx=(8, 0), pady=3, ipady=4)
            entry_vars[key] = v

        tk.Frame(outer, bg=C_BORDER, height=1).pack(fill=tk.X, pady=(16, 14))

        btn_row = tk.Frame(outer, bg=C_CARD)
        btn_row.pack(anchor='e')

        def _on_save():
            new_meta = {key: v.get().strip() for key, v in entry_vars.items()}
            existing = dict(meta)
            existing.update(new_meta)
            dlg.destroy()
            self._save_metadata(existing)

        tk.Button(
            btn_row, text="Cancel", font=F_LABEL,
            bg=C_CARD, fg=C_TEXT2,
            activebackground=C_BORDER, activeforeground=C_TEXT,
            relief=tk.FLAT, bd=0, padx=14, pady=5, cursor="hand2",
            highlightbackground=C_BORDER, highlightthickness=1,
            command=dlg.destroy,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            btn_row, text="Save", font=("Segoe UI", 10, "bold"),
            bg=C_ACCENT, fg=C_BG,
            activebackground="#2B6CB0", activeforeground=C_BG,
            relief=tk.FLAT, bd=0, padx=20, pady=5, cursor="hand2",
            command=_on_save,
        ).pack(side=tk.LEFT)

        dlg.bind('<Return>', lambda e: _on_save())
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        root = self.winfo_toplevel()
        dlg.update_idletasks()
        x = root.winfo_x() + (root.winfo_width()  - dlg.winfo_width())  // 2
        y = root.winfo_y() + (root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self.wait_window(dlg)

    # ── Couverture de relecture ───────────────────────────────────────────────

    _COVERAGE_FLUSH_EVERY = 25

    def _flush_coverage(self, force=False):
        """Écrit la couverture de la caméra courante dans correction_state.json.

        Appelée régulièrement pendant la navigation, et pas seulement à la
        sauvegarde : l'application n'a aucun gestionnaire de fermeture, donc une
        caméra relue intégralement puis fermée sans rien changer — exactement le
        cas que ce compteur existe pour rendre visible — laisserait sinon zéro
        trace.
        """
        if not self._drop_dir or not self._cam_id or not self._seen_frames:
            return
        if not force and (len(self._seen_frames) - self._seen_flushed
                          < self._COVERAGE_FLUSH_EVERY):
            return
        correction_state.record_coverage(
            self._drop_dir, self._cam_id, self._seen_frames,
            frames_total=len(self._frames),
            cameras_total=len(self._discover_cameras(self._drop_dir)),
        )
        self._seen_flushed = len(self._seen_frames)

    def _update_correction_state_label(self, force=False):
        """Rafraîchit la ligne de tampon, sans toucher au disque pour rien.

        _render_frame est aussi branché sur <Configure> : pendant un
        redimensionnement il part des dizaines de fois par seconde. On ne relit
        correction_state.json que si l'un des éléments qui composent la ligne a
        bougé.
        """
        lbl = getattr(self, '_lbl_correction_state', None)
        if lbl is None:
            return
        key = (self._drop_dir, self._cam_id,
               len(self._seen_frames), len(self._frames))
        if not force and key == getattr(self, '_state_label_key', None):
            return
        self._state_label_key = key
        lbl.config(text=correction_state.tab_summary(
            self._drop_dir, self._cam_id,
            frames_seen=self._seen_frames,
            frames_total=len(self._frames),
        ))

    # ── Régénération des sorties (hors thread Tk) ─────────────────────────────

    _REGEN_TIMEOUT_S = 900   # 15 min : large, mais fini

    def _set_busy(self, label):
        self._busy = True
        for w, st in ((self._btn_save, tk.DISABLED),
                      (self._cam_combo, tk.DISABLED),
                      (self._drop_combo, tk.DISABLED)):
            try:
                w.config(state=st)
            except tk.TclError:
                pass
        self._lbl_correction_state.config(text=label)

    def _clear_busy(self):
        self._busy = False
        try:
            self._btn_save.config(state=tk.NORMAL)
            self._cam_combo.config(state='readonly')
            self._drop_combo.config(state='readonly')
        except tk.TclError:
            pass
        self._update_correction_state_label(force=True)

    def _run_generators(self, steps, on_success, on_error, busy_label):
        """Exécute les scripts de génération hors du thread Tk.

        Ces appels bloquaient la boucle principale : régénérer la campagne relit
        tous les drops et compte les frames de chaque caméra, ce que Windows
        affiche en « Ne répond pas ». Depuis que `_campaign_regen_dir()` déclenche
        cette régénération même quand on a ouvert un drop seul, le gel est devenu
        le cas normal et non plus l'exception. Un `timeout` s'ajoute au passage :
        sans lui, un sous-processus bloqué figeait l'application sans issue.

        `on_success` et `on_error` sont rappelés sur le thread Tk via `after`.
        """
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        self._set_busy(busy_label)

        outcome  = queue.Queue()
        timeout  = self._REGEN_TIMEOUT_S

        def worker():
            for cmd in steps:
                try:
                    subprocess.run(
                        cmd, check=True, cwd=PROJECT_ROOT, env=env,
                        capture_output=True, text=True,
                        # Sans encoding explicite, la sortie de l'enfant est
                        # décodée dans l'encodage local (cp1252) : un chemin
                        # accentué levait une UnicodeDecodeError à l'intérieur
                        # même du gestionnaire d'erreur.
                        encoding='utf-8', errors='replace',
                        timeout=timeout,
                    )
                except subprocess.CalledProcessError as e:
                    outcome.put(('error', e.stderr or str(e)))
                    return
                except subprocess.TimeoutExpired:
                    outcome.put(('error',
                                 f"No answer after {timeout // 60} minutes."))
                    return
                except OSError as e:
                    outcome.put(('error', str(e)))
                    return
            outcome.put(('ok', None))

        # Le thread de travail ne touche à rien de Tk : il dépose son résultat
        # dans une file que le thread principal vient relever. Appeler after()
        # depuis le thread de travail « marche » le plus souvent, mais échoue
        # dès que la boucle principale n'est pas en cours d'exécution
        # (RuntimeError: main thread is not in main loop).
        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                status, payload = outcome.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            # Libéré ici et non dans les rappels : un appelant qui oublierait
            # de le faire laisserait l'interface verrouillée pour de bon.
            self._clear_busy()
            if status == 'ok':
                on_success()
            else:
                on_error(payload)

        self.after(150, poll)

    def _campaign_steps(self, campaign_dir):
        campaign_csv  = os.path.join(campaign_dir, 'classification_campaign.csv')
        campaign_xlsx = os.path.join(campaign_dir, 'classification_campaign.xlsx')
        return [
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_campaign_csv.py'),
             '--results_dir', campaign_dir, '--output', campaign_csv],
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_campaign_excel.py'),
             '--campaign_csv', campaign_csv, '--results_dir', campaign_dir,
             '--output', campaign_xlsx],
        ]

    def _campaign_regen_dir(self):
        """Campaign folder whose CSV/Excel must be refreshed after a save.

        self._campaign_dir is only set when the user picked the campaign folder
        itself. But the pipeline writes every drop flat into results/ and puts
        the campaign files at its root, so the parent of a drop *is* the
        campaign: opening a single drop used to leave classification_campaign
        silently stale — and that is the file analyses are run on.

        Only ever refresh what already exists. The pipeline produces no campaign
        files for a single-drop run, and we must not invent them here.
        """
        if self._campaign_dir:
            return self._campaign_dir
        if self._drop_dir:
            parent = os.path.dirname(os.path.normpath(self._drop_dir))
            if os.path.isfile(os.path.join(parent, 'classification_campaign.csv')):
                return parent
        return None

    def _save_metadata(self, meta):
        if not self._drop_dir:
            return

        meta_path = os.path.join(self._drop_dir, 'drop_metadata.json')
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f"[ERROR] Failed to write drop_metadata.json: {e}\n", "error")
            messagebox.showerror("Metadata error", f"Failed to write metadata:\n{e}")
            return

        # Patch metadata columns in each cam CSV
        META_COLS = ['campaign', 'location', 'site', 'drop_id', 'date',
                     'latitude', 'longitude', 'habitat', 'visibility', 'depth']
        csv_dir = os.path.join(self._drop_dir, 'csv')
        if os.path.isdir(csv_dir):
            for cam_csv in glob.glob(os.path.join(csv_dir, '*_classification.csv')):
                if os.path.getsize(cam_csv) == 0:
                    continue
                try:
                    df = pd.read_csv(cam_csv)
                    if df.empty:
                        continue
                    for col in META_COLS:
                        if col in df.columns:
                            df[col] = meta.get(col, df[col])
                    df.to_csv(cam_csv, index=False)
                except Exception as e:
                    self._log(f"[WARN] Could not patch {os.path.basename(cam_csv)}: {e}\n", "warn")

        # Regenerate drop CSV + Excel — hors thread Tk, cf. _run_generators
        drop_csv  = os.path.join(self._drop_dir, 'classification_drop.csv')
        excel_out = os.path.join(self._drop_dir, 'classification_drop.xlsx')
        drop_dir  = self._drop_dir
        campaign_dir = self._campaign_regen_dir()

        drop_steps = [
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_drop_csv.py'),
             '--drop_results', drop_dir, '--output', drop_csv],
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_excel.py'),
             '--input', drop_csv, '--output', excel_out,
             '--drop_dir', drop_dir],
        ]

        def finish():
            self._log(f"[OK] Metadata saved — {os.path.basename(drop_dir)}\n", "ok")
            messagebox.showinfo("Saved", "Metadata saved and files regenerated.")

        def drop_failed(err):
            self._log(f"[ERROR] CSV/Excel regeneration failed: {err}\n", "error")
            messagebox.showerror("Metadata save error",
                                 f"Metadata saved but CSV/Excel regeneration failed:\n{err}")

        def campaign_failed(err):
            self._log(f"[ERROR] Campaign regeneration failed: {err}\n", "error")
            messagebox.showerror("Campaign error",
                                 f"Metadata saved but campaign regeneration failed:\n{err}")

        def drop_done():
            if not campaign_dir:
                finish()
                return
            self._run_generators(
                self._campaign_steps(campaign_dir),
                on_success=finish, on_error=campaign_failed,
                busy_label="Regenerating the campaign files — please wait…",
            )

        self._run_generators(
            drop_steps, on_success=drop_done, on_error=drop_failed,
            busy_label="Regenerating the drop files — please wait…",
        )

    # ── Double-clic canvas → popup crop ──────────────────────────────────────

    def _on_canvas_double_click(self, event):
        if not self._frames or self._draw_mode:
            return
        fr    = self._frames[self._frame_idx]
        scale = self._render_scale
        ox    = self._render_ox
        oy    = self._render_oy

        best_idx  = None
        best_area = float('inf')
        for i, det in enumerate(fr['detections']):
            x1, y1, x2, y2 = det['bbox']
            if (ox + x1 * scale <= event.x <= ox + x2 * scale and
                    oy + y1 * scale <= event.y <= oy + y2 * scale):
                area = (x2 - x1) * (y2 - y1)
                if area < best_area:
                    best_area = area
                    best_idx  = i

        if best_idx is None:
            return
        det = fr['detections'][best_idx]
        if not det.get('det_file') or not self._drop_dir or not self._cam_id:
            return
        img_path = os.path.join(
            self._drop_dir, f'{self._cam_id}_detections', det['det_file']
        )
        if os.path.isfile(img_path):
            self._show_crop_popup(img_path)

    def _show_crop_popup(self, img_path):
        try:
            pil_orig = Image.open(img_path).convert('RGB')
        except Exception:
            return

        orig_w, orig_h = pil_orig.size
        init_zoom = min(1.0, 500 / orig_w, 500 / orig_h)
        state = {'zoom': init_zoom, 'tk_img': None}

        dlg = tk.Toplevel(self)
        dlg.configure(bg=C_CANVAS_BG)
        dlg.resizable(True, True)
        dlg.transient(self.winfo_toplevel())

        popup_canvas = tk.Canvas(dlg, bg=C_CANVAS_BG, highlightthickness=0)
        popup_canvas.pack(fill=tk.BOTH, expand=True)

        hint = tk.Label(
            dlg, text="Scroll wheel: zoom  —  Esc: close",
            font=F_SMALL, bg=C_CANVAS_BG, fg=C_TEXT2,
        )
        hint.pack(pady=(0, 4))

        def _render_popup():
            zoom  = state['zoom']
            dw    = max(int(orig_w * zoom), 1)
            dh    = max(int(orig_h * zoom), 1)
            img   = pil_orig.resize((dw, dh), Image.LANCZOS)
            tk_im = ImageTk.PhotoImage(img)
            state['tk_img'] = tk_im
            popup_canvas.config(width=dw, height=dh)
            popup_canvas.delete('all')
            popup_canvas.create_image(0, 0, anchor='nw', image=tk_im)
            dlg.title(
                f"{os.path.basename(img_path)}  —  "
                f"{orig_w}×{orig_h} px  (×{zoom:.2f})"
            )

        def _on_popup_wheel(e):
            factor   = 1.2 if e.delta > 0 else 1 / 1.2
            new_zoom = max(0.1, min(state['zoom'] * factor, 10.0))
            if abs(new_zoom - state['zoom']) < 0.001:
                return
            state['zoom'] = new_zoom
            _render_popup()

        popup_canvas.bind('<MouseWheel>', _on_popup_wheel)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        _render_popup()

        dlg.update_idletasks()
        root = self.winfo_toplevel()
        px = root.winfo_rootx() + (root.winfo_width()  - dlg.winfo_width())  // 2
        py = root.winfo_rooty() + (root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{px}+{py}")

    # ── Export crops ──────────────────────────────────────────────────────────

    def _export_crops(self):
        if not self._drop_dir or not self._cam_id:
            messagebox.showwarning(
                "No drop loaded", "Please open a results folder first."
            )
            return

        dest_root = filedialog.askdirectory(
            title="Select destination folder (e.g. crop_retraining)",
        )
        if not dest_root:
            return

        det_dir       = os.path.join(self._drop_dir, f'{self._cam_id}_detections')
        exported      = 0
        skipped_small = 0
        skipped_miss  = 0
        skipped_added = 0

        for fr in self._frames:
            for det in fr['detections']:
                if det['status'] != 'ok':
                    continue
                if not det.get('det_file'):
                    skipped_added += 1
                    continue
                src = os.path.join(det_dir, det['det_file'])
                if not os.path.isfile(src):
                    skipped_miss += 1
                    continue
                try:
                    img = Image.open(src).convert('RGB')
                except Exception:
                    skipped_miss += 1
                    continue
                w, h = img.size
                if w < 64 or h < 64:
                    skipped_small += 1
                    continue

                family_dir = os.path.join(dest_root, det['family'])
                os.makedirs(family_dir, exist_ok=True)
                stem     = os.path.splitext(det['det_file'])[0]
                dst      = os.path.join(family_dir, f'{stem}.png')
                img.save(dst, 'PNG')
                exported += 1

        parts = [f"{exported} crop(s) exported"]
        if skipped_added:
            parts.append(f"{skipped_added} manually added (no crop file, skipped)")
        if skipped_small:
            parts.append(f"{skipped_small} skipped (< 64×64 px)")
        if skipped_miss:
            parts.append(f"{skipped_miss} file(s) not found")
        msg = "\n".join(parts)
        messagebox.showinfo("Export complete", msg)
        self._log(f"[OK] Export crops : {msg.replace(chr(10), ' | ')}\n", "ok")

    # ── Sauvegarde ────────────────────────────────────────────────────────────

    def _save(self):
        if not self._dirty or not self._drop_dir or not self._cam_id:
            return

        cam_csv_path = os.path.join(
            self._drop_dir, 'csv', f'{self._cam_id}_classification.csv'
        )

        if os.path.isfile(cam_csv_path) and os.path.getsize(cam_csv_path) > 0:
            orig_df    = pd.read_csv(cam_csv_path)
            cols       = list(orig_df.columns)
            # Ensure genus/species columns present
            for _col in ('genus', 'species'):
                if _col not in cols:
                    _ins = cols.index('family') + 1 if 'family' in cols else len(cols)
                    cols.insert(_ins, _col)
            const_cols = [c for c in cols
                          if c not in ('frame', 'family', 'genus', 'species',
                                       'count', 'confidence', 'camera')]
            frame_meta = {}
            for _, r in orig_df.iterrows():
                fnum = int(r['frame'])
                if fnum not in frame_meta:
                    frame_meta[fnum] = {c: r[c] for c in const_cols if c in orig_df.columns}
            n_frames_val = (orig_df['n_frames'].iloc[0]
                            if 'n_frames' in cols and not orig_df.empty
                            else len(self._frames))
        else:
            cols         = ['camera', 'frame', 'family', 'genus', 'species', 'count', 'confidence']
            frame_meta   = {}
            n_frames_val = len(self._frames)

        # Fallback metadata pour frames absentes du CSV (nouvelles détections sur frames vierges)
        _fallback_meta = {}
        if frame_meta:
            _sorted_fns = sorted(frame_meta.keys())
            _ref        = frame_meta[_sorted_fns[0]]
            _non_time   = [c for c in const_cols if c not in ('time_s', 'time_after_t0')]
            _const_vals = {c: _ref.get(c) for c in _non_time if c in _ref}
            if 'n_frames' in const_cols:
                _const_vals['n_frames'] = n_frames_val

            def _build_pts(col):
                pts = []
                for _fn2 in _sorted_fns:
                    try:
                        fv = float(frame_meta[_fn2].get(col, float('nan')))
                        if not math.isnan(fv):
                            pts.append((_fn2, fv))
                    except (TypeError, ValueError):
                        pass
                return pts

            def _interp_val(pts, fn_target):
                if not pts:
                    return None
                if len(pts) == 1:
                    return pts[0][1]
                for i in range(len(pts) - 1):
                    fn0, t0 = pts[i]; fn1, t1 = pts[i + 1]
                    if fn0 <= fn_target <= fn1:
                        return round(t0 + (t1 - t0) * (fn_target - fn0) / (fn1 - fn0), 2) if fn1 != fn0 else t0
                fn0, t0 = (pts[0][0], pts[0][1]) if fn_target < pts[0][0] else (pts[-2][0], pts[-2][1])
                fn1, t1 = (pts[1][0], pts[1][1]) if fn_target < pts[0][0] else (pts[-1][0], pts[-1][1])
                return round(t0 + (t1 - t0) * (fn_target - fn0) / (fn1 - fn0), 2) if fn1 != fn0 else t0

            _ts_pts = _build_pts('time_s')        if 'time_s'        in const_cols else []
            _t0_pts = _build_pts('time_after_t0') if 'time_after_t0' in const_cols else []

            for _fr2 in self._frames:
                _fn2 = _fr2['frame_num']
                if _fn2 not in frame_meta:
                    _fb = dict(_const_vals)
                    if _ts_pts:
                        _fb['time_s'] = _interp_val(_ts_pts, _fn2)
                    if _t0_pts:
                        _fb['time_after_t0'] = _interp_val(_t0_pts, _fn2)
                    _fallback_meta[_fn2] = _fb

        rows = []
        for fr in self._frames:
            for det in fr['detections']:
                if det['status'] == 'fp':
                    continue
                is_unknown = det['family'] == 'inconnu'
                base               = dict(frame_meta.get(fr['frame_num'], _fallback_meta.get(fr['frame_num'], {})))
                base['camera']     = self._cam_id
                base['frame']      = fr['frame_num']
                base['family']     = det['family']
                base['genus']      = det.get('genus', '') or ('inconnu' if is_unknown else '')
                base['species']    = det.get('species', '') or ('inconnu' if is_unknown else '')
                base['count']      = 1
                base['confidence'] = det['confidence']
                if 'n_frames' in cols and 'n_frames' not in base:
                    base['n_frames'] = n_frames_val
                rows.append(base)

        out_df = (pd.DataFrame(rows, columns=cols) if rows
                  else pd.DataFrame(columns=cols))
        if not out_df.empty:
            out_df = out_df.sort_values(['frame', 'family']).reset_index(drop=True)

        os.makedirs(os.path.dirname(cam_csv_path), exist_ok=True)
        out_df.to_csv(cam_csv_path, index=False)

        # Mettre à jour les .txt de classification pour résister à un re-run pipeline
        cls_dir = os.path.join(self._drop_dir, f'{self._cam_id}_classifications')
        if os.path.isdir(cls_dir):
            for fr in self._frames:
                for det in fr['detections']:
                    if not det.get('det_file'):
                        continue  # détection ajoutée manuellement, pas de .txt
                    det_id   = os.path.splitext(det['det_file'])[0]
                    cls_path = os.path.join(cls_dir, fr['frame_id'], f'{det_id}.txt')
                    if not os.path.isfile(cls_path):
                        continue
                    content = ('fp: 0.0\n' if det['status'] == 'fp'
                               else f"{det['family']}: {det['confidence']}\n")
                    try:
                        with open(cls_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except Exception:
                        pass

        # Sauvegarde du sidecar pour les détections ajoutées manuellement
        _manual_dets = {}
        for _fr in self._frames:
            _added = [d for d in _fr['detections'] if d.get('det_file') is None]
            if _added:
                _manual_dets[str(_fr['frame_num'])] = [
                    {
                        'bbox':        d['bbox'],
                        'family':      d['family'],
                        'family_orig': d.get('family_orig', d['family']),
                        'genus':       d.get('genus', ''),
                        'species':     d.get('species', ''),
                        'confidence':  d.get('confidence', 1.0),
                        'status':      d['status'],
                    }
                    for d in _added
                ]
        _manual_path = os.path.join(self._drop_dir, 'csv', f'{self._cam_id}_manual_detections.json')
        try:
            if _manual_dets:
                with open(_manual_path, 'w', encoding='utf-8') as _mf:
                    json.dump(_manual_dets, _mf, ensure_ascii=False, indent=2)
            elif os.path.isfile(_manual_path):
                os.remove(_manual_path)
        except Exception as _e:
            self._log(f"[WARN] Manual detections sidecar write error: {_e}\n", "error")

        # Trace de la correction manuelle — lue par les générateurs Excel pour
        # dire, en tête de l'onglet Indicators, sur quoi reposent MeanCount et
        # TOFS. Écrite AVANT la régénération, sinon le tampon aurait un tour de
        # retard. Les compteurs sont recalculés depuis l'état courant (et non
        # incrémentés), donc sauvegarder deux fois ne les gonfle pas.
        _fp_ids, _added, _relabel = set(), 0, {}
        for _fr in self._frames:
            for _det in _fr['detections']:
                if _det.get('det_file') is None:
                    _added += 1
                    continue
                _id = os.path.splitext(_det['det_file'])[0]
                if _det['status'] == 'fp':
                    _fp_ids.add(_id)
                else:
                    # Famille courante + famille lue au chargement : le module
                    # d'état tranche à partir de la famille automatique qu'il a
                    # gardée, ce que cette session ne peut pas connaître (le
                    # .txt est réécrit à chaque sauvegarde).
                    _relabel[_id] = (_det['family'],
                                     _det.get('family_orig', _det['family']))
        correction_state.record_camera(
            self._drop_dir, self._cam_id, _fp_ids, _added, _relabel,
            frames_seen=self._seen_frames,
            frames_total=len(self._frames),
            cameras_total=len(self._discover_cameras(self._drop_dir)),
        )
        self._seen_flushed = len(self._seen_frames)

        drop_csv  = os.path.join(self._drop_dir, 'classification_drop.csv')
        excel_out = os.path.join(self._drop_dir, 'classification_drop.xlsx')
        drop_dir  = self._drop_dir
        cam_id    = self._cam_id
        campaign_dir = self._campaign_regen_dir()

        drop_steps = [
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_drop_csv.py'),
             '--drop_results', drop_dir, '--output', drop_csv],
            [sys.executable,
             os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_excel.py'),
             '--input', drop_csv, '--output', excel_out,
             '--drop_dir', drop_dir],
        ]

        def finish(campaign_done):
            self._undo_stack.clear()
            self._dirty = False
            self._update_save_btn()
            self._log(f"[OK] Corrections saved — "
                      f"{os.path.basename(drop_dir)} / {cam_id}\n", "ok")
            msg = "Corrections saved and files regenerated."
            if campaign_done:
                msg += "\nCampaign CSV and Excel updated."
            messagebox.showinfo("Saved", msg)

        def drop_failed(err):
            # Les corrections sont déjà sur le disque, mais les sorties ne les
            # reflètent pas : on laisse le bouton en « modifié » pour le dire.
            self._log(f"[ERROR] CSV/Excel regeneration failed: {err}\n", "error")
            messagebox.showerror("Save error", f"CSV/Excel regeneration failed:\n{err}")

        def campaign_failed(err):
            self._log(f"[ERROR] Campaign regeneration failed: {err}\n", "error")
            messagebox.showerror(
                "Campaign error",
                f"Drop saved but campaign regeneration failed:\n{err}",
            )
            finish(campaign_done=False)   # le drop, lui, est bien à jour

        def drop_done():
            if not campaign_dir:
                finish(campaign_done=False)
                return
            self._run_generators(
                self._campaign_steps(campaign_dir),
                on_success=lambda: finish(campaign_done=True),
                on_error=campaign_failed,
                busy_label="Regenerating the campaign files — please wait…",
            )

        self._run_generators(
            drop_steps, on_success=drop_done, on_error=drop_failed,
            busy_label="Regenerating the drop files — please wait…",
        )
