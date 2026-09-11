"""
RENAI — Onglet de caractérisation d'habitat
Vue "360°" sobre et en lecture seule : reconstruit une bande panoramique
à partir de la frame du milieu de chaque caméra pour un drop donné.
"""

import glob
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core', 'run'))
import correction_state

# ── Palette sombre (identique à correction_tab.py, pour cohérence visuelle) ─
C_BG          = "#0F1117"
C_CARD        = "#1A1D27"
C_BORDER      = "#252836"
C_TEXT        = "#E2E8F0"
C_TEXT2       = "#7B879A"
C_BTN_NEUTRAL = "#2D3748"
C_CANVAS_BG   = "#070A0E"

F_LABEL = ("Segoe UI", 10)

STRIP_HEIGHT = 420   # hauteur cible (px) de chaque volet caméra
HEADER_H     = 28    # bande d'en-tête (labels caméra)


class HabitatTab(tk.Frame):

    def __init__(self, parent, results_root, get_default_drop_dir=None, log_fn=None):
        super().__init__(parent, bg=C_BG)
        self.results_root          = results_root
        self._get_default_drop_dir = get_default_drop_dir
        self._log                  = log_fn or (lambda *a, **k: None)

        self._campaign_dir = None
        self._drop_dir     = None
        self._drop_var     = tk.StringVar()
        self._tk_img        = None   # ref GC — PhotoImage doit survivre au-delà de la méthode

        self._build_ui()

    # ── Construction UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        top = tk.Frame(self, bg=C_CARD,
                       highlightbackground=C_BORDER, highlightthickness=1)
        top.pack(fill=tk.X, padx=6, pady=(6, 4))
        top_inner = tk.Frame(top, bg=C_CARD, padx=10, pady=8)
        top_inner.pack(fill=tk.X)

        tk.Button(
            top_inner, text="Open ···", font=F_LABEL,
            bg=C_BTN_NEUTRAL, fg=C_TEXT,
            activebackground=C_BORDER, activeforeground=C_TEXT,
            relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2",
            command=self._open_drop,
        ).pack(side=tk.LEFT)

        self._lbl_drop_path = tk.Label(
            top_inner, text="No folder selected",
            font=F_LABEL, bg=C_CARD, fg=C_TEXT2,
        )
        self._lbl_drop_path.pack(side=tk.LEFT, padx=(12, 0))

        drop_frame = tk.Frame(top_inner, bg=C_CARD)
        drop_frame.pack(side=tk.RIGHT)
        tk.Label(drop_frame, text="Drop:", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT2).pack(side=tk.LEFT)
        self._drop_combo = ttk.Combobox(
            drop_frame, textvariable=self._drop_var,
            state='readonly', width=18, font=F_LABEL,
        )
        self._drop_combo.pack(side=tk.LEFT, padx=(6, 0))
        self._drop_combo.bind('<<ComboboxSelected>>', self._on_drop_selected)

        self._lbl_habitat = tk.Label(
            self, text="Recorded habitat: —", font=("Segoe UI", 10, "bold"),
            bg=C_BG, fg=C_TEXT, anchor='w',
        )
        self._lbl_habitat.pack(fill=tk.X, padx=12, pady=(4, 4))

        canvas_card = tk.Frame(self, bg=C_CANVAS_BG,
                               highlightbackground=C_BORDER, highlightthickness=1)
        canvas_card.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        hsb = ttk.Scrollbar(canvas_card, orient=tk.HORIZONTAL)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self._canvas = tk.Canvas(canvas_card, bg=C_CANVAS_BG, highlightthickness=0,
                                  xscrollcommand=hsb.set)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        hsb.config(command=self._canvas.xview)

        self._canvas.create_text(
            20, 20, anchor='nw', fill=C_TEXT2, font=F_LABEL,
            text="Open a drop or campaign folder to view its habitat strip.",
        )

    # ── Ouverture ─────────────────────────────────────────────────────────────

    def _open_drop(self):
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

        cams = self._discover_cameras(folder)
        if cams:
            self._campaign_dir = None
            drop_name = os.path.basename(folder)
            self._drop_dir = folder
            self._lbl_drop_path.config(text=drop_name)
            self._drop_combo.config(values=[drop_name])
            self._drop_var.set(drop_name)
            self._load_drop_view()
            return

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
        self._drop_dir = os.path.join(folder, drops[0])
        self._load_drop_view()

    def _discover_cameras(self, folder):
        # Définition partagée avec l'onglet Correction manuelle — cf.
        # core/run/correction_state.py
        return correction_state.camera_ids(folder)

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

    def _on_drop_selected(self, event=None):
        drop = self._drop_var.get()
        if not self._campaign_dir:
            return
        self._drop_dir = os.path.join(self._campaign_dir, drop)
        self._load_drop_view()

    # ── Chargement / rendu ───────────────────────────────────────────────────

    def _load_drop_view(self):
        self._load_habitat_label()
        self._render_strip()

    def _load_habitat_label(self):
        meta_path = os.path.join(self._drop_dir, 'drop_metadata.json')
        habitat = '—'
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding='utf-8') as f:
                    meta = json.load(f)
                habitat = str(meta.get('habitat', '') or '—')
            except Exception:
                pass
        self._lbl_habitat.config(text=f"Recorded habitat: {habitat}")

    def _middle_frame_path(self, cam_id):
        frame_dir = os.path.join(self._drop_dir, f'{cam_id}_frames')
        files = sorted(glob.glob(os.path.join(frame_dir, '*.jpg')))
        if not files:
            return None
        return files[len(files) // 2]

    def _render_strip(self):
        self._canvas.delete('all')
        cams = self._discover_cameras(self._drop_dir)
        if not cams:
            self._canvas.create_text(
                20, 20, anchor='nw', fill=C_TEXT2, font=F_LABEL,
                text="No camera frames found for this drop.",
            )
            return

        panes = []
        for cam_id in cams:
            img = None
            fp = self._middle_frame_path(cam_id)
            if fp:
                try:
                    img = Image.open(fp).convert("RGB")
                    ratio = STRIP_HEIGHT / img.height
                    img = img.resize(
                        (max(1, int(img.width * ratio)), STRIP_HEIGHT), Image.LANCZOS
                    )
                except Exception:
                    img = None
            if img is None:
                img = Image.new("RGB", (STRIP_HEIGHT, STRIP_HEIGHT), (40, 42, 54))
            panes.append((cam_id, img))

        gap     = 2
        total_w = sum(im.width for _, im in panes) + gap * (len(panes) - 1)
        strip   = Image.new("RGB", (total_w, HEADER_H + STRIP_HEIGHT), (15, 17, 23))

        x = 0
        for _, img in panes:
            strip.paste(img, (x, HEADER_H))
            x += img.width + gap

        self._tk_img = ImageTk.PhotoImage(strip)
        self._canvas.create_image(0, 0, anchor='nw', image=self._tk_img)

        # Labels caméra dessinés par le canvas Tk (plus net que du texte PIL)
        x = 0
        for cam_id, img in panes:
            self._canvas.create_text(
                x + 8, HEADER_H // 2, anchor='w', fill=C_TEXT,
                font=("Segoe UI", 10, "bold"), text=f"Cam {cam_id}",
            )
            x += img.width + gap

        self._canvas.config(scrollregion=(0, 0, total_w, HEADER_H + STRIP_HEIGHT))
