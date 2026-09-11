"""
RENAI — Underwater video processing pipeline
Interface graphique principale (tkinter)
"""

import os
import re
import sys
import queue
import ctypes
import platform
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path
import yaml

from core.version import __version__
from ui.correction_tab import CorrectionTab
from ui.habitat_tab import HabitatTab

if sys.platform == "win32":
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RENAI.App")

# ── Palette ───────────────────────────────────────────────────────────────────

C_HEADER_BG   = "#1A365D"
C_BG          = "#F5F7FA"
C_CARD        = "#FFFFFF"
C_BORDER      = "#D9E2EC"
C_TEXT        = "#1F2933"
C_TEXT2       = "#52606D"
C_ACCENT      = "#2B6CB0"
C_SUCCESS     = "#2F855A"
C_ERROR       = "#C53030"
C_WARNING     = "#DD6B20"
C_CONSOLE_BG  = "#1E1E2E"
C_CONSOLE_FG  = "#E8E8E8"
C_LOG_ERROR   = "#FC8181"
C_LOG_OK      = "#68D391"
C_LOG_INFO    = "#63B3ED"
C_LOG_WARN    = "#F6AD55"
C_LOG_CMD     = "#A0AEC0"

C_BTN_PRIMARY   = "#276749"   # Start All — vert primaire
C_BTN_SECONDARY = "#2B5282"   # Start detection only — bleu secondaire
C_BTN_DANGER    = "#9B2335"   # Stop — rouge danger
C_BTN_NEUTRAL   = "#4A5568"   # Open Results — gris neutre

C_ROW_OK        = "#F0FFF4"
C_ROW_ERR       = "#FFF5F5"
C_ROW_RUN       = "#FFFBEB"

# ── Polices ───────────────────────────────────────────────────────────────────

F_LABEL   = ("Segoe UI", 10)
F_BTN     = ("Segoe UI", 10, "bold")
F_MONO    = ("Consolas", 10)
F_SMALL   = ("Segoe UI", 8)
F_BRAND   = ("Segoe UI", 14, "bold")
F_BRAND2  = ("Segoe UI", 9)

# ── Constantes ────────────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEO_EXTS   = {".mp4", ".mov", ".avi", ".mkv"}
DEFAULT_DIR  = os.path.join(PROJECT_ROOT, "drops")
CONFIG_PATH  = os.path.join(PROJECT_ROOT, "config.yaml")

# ── Regex pour le panneau de suivi ────────────────────────────────────────────

_RE_CAM        = re.compile(r'\[CAM\]\s+Camera\s+(\S+)')
_RE_STEP_START = re.compile(r'\[STEP\]\s+\[(\d+)/10\]\s+(.+)')
_RE_STEP_OK    = re.compile(r'\[OK\]\s+\[(\d+)/10\]\s+(.+)')
_RE_STEP_ERR   = re.compile(r'\[ERROR\]\s+\[(\d+)/10\]')
_RE_CAM_LABEL  = re.compile(r'cam\s+(\S+)$')

_STEP_COL = {
    1: 'clap', 2: 'extraction',
    3: 'detection', 4: 'detection',
    5: 'classification', 6: 'classification',
}

_FULL_META_FIELDS = (
    'campaign', 'location', 'site', 'drop_id', 'date',
    'latitude', 'longitude', 'habitat', 'visibility', 'depth',
)

_S_WAIT    = 'Waiting'
_S_RUNNING = '⏳ Running'
_S_OK      = '✅ Done'
_S_ERROR   = '❌ Error'


# ── Application ───────────────────────────────────────────────────────────────

class RenaiApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title(f"RENAI v{__version__} — Underwater video processing pipeline")
        self.geometry("1020x760")
        self.minsize(780, 580)
        self.configure(bg=C_BG)

        # Taskbar/window icon. iconbitmap(default=...) is sufficient on Windows:
        # it sets the icon for this window and every future Toplevel (dialogs).
        # If the taskbar ever shows Tk's default feather instead of the fish,
        # the cause is NOT this code: Windows groups every window sharing the
        # AppUserModelID "RENAI.App" (renai.v1, renai.mvp, installed RENAI)
        # under ONE taskbar button whose icon comes from the oldest live window
        # of the group. A stale instance started while this .ico was missing
        # shows the feather for the whole group until it exits — no API call
        # from a newer instance can override it (verified empirically
        # 01/07/2026, incl. WM_SETICON/SetClassLongPtr). Fix: close stale
        # RENAI instances; keep the .ico present so no instance ever starts
        # without it.
        _icon = os.path.join(PROJECT_ROOT, "assets", "icon_renai.ico")
        if os.path.exists(_icon):
            self.iconbitmap(default=_icon)
        else:
            print(f"[WARN] Icon not found, taskbar will show the Tk default: {_icon}",
                  file=sys.stderr)

        self._runner  = None
        self._running = False
        self._queue: queue.Queue = queue.Queue()

        try:
            with open(CONFIG_PATH, encoding='utf-8') as _f:
                self._results_dir = yaml.safe_load(_f).get('results_dir', 'results')
        except Exception:
            self._results_dir = 'results'

        self._track_mode_key    = 'all'
        self._track_cams: dict  = {}
        self._track_cam_order: list = []
        self._track_step_count  = 0
        self._track_step_total  = 0
        self._track_current_cam = ''

        self._folder_mode      = 'drop'
        self._discovered_drops: list = []
        self._stop_campaign    = threading.Event()

        self._track_drops: dict      = {}
        self._track_drop_order: list = []
        self._track_current_drop     = ''

        self._csv_mode_var    = tk.StringVar(value='full')
        self._meta_campagne   = tk.StringVar()
        self._meta_localisa   = tk.StringVar()
        self._meta_site       = tk.StringVar()
        self._meta_latitude   = tk.StringVar()
        self._meta_longitude  = tk.StringVar()
        self._meta_drop_id    = tk.StringVar()
        self._meta_date       = tk.StringVar()
        self._meta_habitat    = tk.StringVar()
        self._meta_visib      = tk.StringVar()
        self._meta_profondeur = tk.StringVar()

        self._export_annot_var  = tk.BooleanVar(value=False)
        self._annot_format_var  = tk.StringVar(value='both')
        self._html_report_var   = tk.BooleanVar(value=False)

        self._vid_format     = tk.StringVar(value='—')
        self._vid_duration   = tk.StringVar(value='—')
        self._vid_resolution = tk.StringVar(value='—')
        self._vid_fps        = tk.StringVar(value='—')
        self._vid_codec      = tk.StringVar(value='—')
        self._vid_size       = tk.StringVar(value='—')

        self._form_current_drop = ''
        self._form_updating     = False
        self._form_save_after   = None

        for sv in (self._meta_campagne, self._meta_localisa, self._meta_site,
                   self._meta_latitude, self._meta_longitude,
                   self._meta_drop_id, self._meta_date,
                   self._meta_habitat, self._meta_visib, self._meta_profondeur):
            sv.trace_add('write', self._on_meta_change)

        self._configure_styles()
        self._build_header()
        self._build_body()
        self._poll_queue()

    # ── Styles ttk ────────────────────────────────────────────────────────────

    def _configure_styles(self):
        s = ttk.Style()
        s.theme_use('clam')

        s.configure('TNotebook', background=C_BG, borderwidth=0)
        s.configure('TNotebook.Tab',
            font=("Segoe UI", 10), padding=(16, 7),
        )
        s.map('TNotebook.Tab',
            background=[('selected', C_CARD), ('!selected', C_BORDER)],
            foreground=[('selected', C_ACCENT), ('!selected', C_TEXT2)],
        )

        s.configure('Track.Treeview',
            background=C_CARD, foreground=C_TEXT,
            fieldbackground=C_CARD, rowheight=30,
            font=("Segoe UI", 10), borderwidth=0,
        )
        s.configure('Track.Treeview.Heading',
            background=C_BG, foreground=C_TEXT2,
            font=("Segoe UI", 9, "bold"), relief=tk.FLAT,
        )
        s.map('Track.Treeview',
            background=[('selected', '#EBF8FF')],
            foreground=[('selected', C_TEXT)],
        )

        s.configure('RENAI.Horizontal.TProgressbar',
            troughcolor=C_BORDER, background=C_SUCCESS,
            thickness=20, borderwidth=0,
        )

    # ── Construction UI ───────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=C_HEADER_BG)
        hdr.pack(fill=tk.X)

        left = tk.Frame(hdr, bg=C_HEADER_BG)
        left.pack(side=tk.LEFT, padx=22, pady=12)

        tk.Label(left, text="RENAI", font=F_BRAND,
                 bg=C_HEADER_BG, fg="#FFFFFF").pack(side=tk.LEFT)
        tk.Label(left, text=f"  v{__version__}", font=("Segoe UI", 10),
                 bg=C_HEADER_BG, fg="#90CDF4").pack(side=tk.LEFT, pady=(6, 0))

        tk.Label(hdr, text="Underwater video processing pipeline",
                 font=F_BRAND2, bg=C_HEADER_BG, fg="#90CDF4",
                 ).pack(side=tk.LEFT, pady=16)

        tk.Button(
            hdr, text=" ? ", font=("Segoe UI", 11, "bold"),
            bg=C_HEADER_BG, fg="#90CDF4",
            activebackground="#2B5282", activeforeground="#FFFFFF",
            relief=tk.FLAT, bd=0, padx=14, pady=10, cursor="hand2",
            command=self._show_help,
        ).pack(side=tk.RIGHT, padx=16)

    def _build_body(self):
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=12)

        self._main_notebook = ttk.Notebook(body, style='TNotebook')
        self._main_notebook.pack(fill=tk.BOTH, expand=True)

        # ── Onglet 1 : Traitement automatique ─────────────────────────────────
        auto_tab = tk.Frame(self._main_notebook, bg=C_BG)
        self._main_notebook.add(auto_tab, text='  Pipeline  ')

        self._build_settings(auto_tab)
        self._build_buttons(auto_tab)

        self._notebook = ttk.Notebook(auto_tab, style='TNotebook')
        self._notebook.pack(fill=tk.BOTH, expand=True)

        tracking_frame = tk.Frame(self._notebook, bg=C_BG)
        self._notebook.add(tracking_frame, text='  Tracking  ')
        self._build_tracking_panel(tracking_frame)

        console_frame = tk.Frame(self._notebook, bg=C_BG)
        self._notebook.add(console_frame, text='  Console  ')
        self._build_console(console_frame)

        # ── Onglet 2 : Correction manuelle ────────────────────────────────────
        self._correction_tab = tk.Frame(self._main_notebook, bg=C_BG)
        self._main_notebook.add(self._correction_tab, text='  Manual Correction  ')
        self._correction_widget = CorrectionTab(
            self._correction_tab,
            results_root=os.path.join(PROJECT_ROOT, self._results_dir),
            get_default_drop_dir=self._get_current_drop_dir,
            log_fn=self._log,
        )
        self._correction_widget.pack(fill=tk.BOTH, expand=True)

        # ── Onglet 3 : Habitats characterization ──────────────────────────────
        self._habitat_tab = tk.Frame(self._main_notebook, bg=C_BG)
        self._main_notebook.add(self._habitat_tab, text='  Habitats characterization  ')
        self._habitat_widget = HabitatTab(
            self._habitat_tab,
            results_root=os.path.join(PROJECT_ROOT, self._results_dir),
            get_default_drop_dir=self._get_current_drop_dir,
            log_fn=self._log,
        )
        self._habitat_widget.pack(fill=tk.BOTH, expand=True)

    def _build_settings(self, parent):
        card = tk.Frame(parent, bg=C_CARD,
                        highlightbackground=C_BORDER, highlightthickness=1)
        card.pack(fill=tk.X, pady=(0, 8))

        inner = tk.Frame(card, bg=C_CARD, padx=14, pady=10)
        inner.pack(fill=tk.X)

        tk.Label(inner, text="PARAMETERS", font=("Segoe UI", 8, "bold"),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor='w', pady=(0, 8))

        # Row 1 — Drop folder
        r1 = tk.Frame(inner, bg=C_CARD)
        r1.pack(fill=tk.X, pady=(0, 6))

        tk.Label(r1, text="Drop folder", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT, width=14, anchor="w").pack(side=tk.LEFT)

        ef = tk.Frame(r1, bg=C_BORDER, padx=1, pady=1)
        ef.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self._folder_var = tk.StringVar(
            value=DEFAULT_DIR if os.path.isdir(DEFAULT_DIR) else PROJECT_ROOT
        )
        self._folder_entry = tk.Entry(
            ef, textvariable=self._folder_var,
            font=F_LABEL, relief=tk.FLAT, bg=C_CARD, fg=C_TEXT,
        )
        self._folder_entry.pack(fill=tk.X, ipady=4, padx=4)

        tk.Button(r1, text="Browse ···", font=F_LABEL, command=self._browse,
                  bg=C_CARD, fg=C_ACCENT,
                  activebackground=C_BORDER, activeforeground=C_ACCENT,
                  relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2",
                  highlightbackground=C_BORDER, highlightthickness=1,
                  ).pack(side=tk.LEFT)

        # Row 2 — Params
        r2 = tk.Frame(inner, bg=C_CARD)
        r2.pack(fill=tk.X)

        tk.Label(r2, text="Delay after clap/start (s)", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT, anchor="w").pack(side=tk.LEFT)

        df = tk.Frame(r2, bg=C_BORDER, padx=1, pady=1)
        df.pack(side=tk.LEFT, padx=(8, 20))
        self._delay_var = tk.StringVar(value="0")
        self._delay_entry = tk.Entry(
            df, textvariable=self._delay_var, font=F_LABEL, width=6,
            relief=tk.FLAT, bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
        )
        self._delay_entry.pack(ipady=4, padx=4)

        tk.Label(r2, text="Frame interval (s)", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT, anchor="w").pack(side=tk.LEFT)

        inf = tk.Frame(r2, bg=C_BORDER, padx=1, pady=1)
        inf.pack(side=tk.LEFT, padx=(8, 20))
        self._interval_var = tk.StringVar(value="1")
        self._interval_entry = tk.Entry(
            inf, textvariable=self._interval_var, font=F_LABEL, width=6,
            relief=tk.FLAT, bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
        )
        self._interval_entry.pack(ipady=4, padx=4)

        tk.Label(r2, text="Max frames (opt.)", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT, anchor="w").pack(side=tk.LEFT)

        mff = tk.Frame(r2, bg=C_BORDER, padx=1, pady=1)
        mff.pack(side=tk.LEFT, padx=(8, 28))
        self._max_frames_var = tk.StringVar(value="")
        self._max_frames_entry = tk.Entry(
            mff, textvariable=self._max_frames_var, font=F_LABEL, width=6,
            relief=tk.FLAT, bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
        )
        self._max_frames_entry.pack(ipady=4, padx=4)

        tk.Label(r2, text="CSV format", font=F_LABEL,
                 bg=C_CARD, fg=C_TEXT).pack(side=tk.LEFT, padx=(0, 8))

        for label, val in [("Full", "full"), ("Minimum", "minimum")]:
            tk.Radiobutton(
                r2, text=label, variable=self._csv_mode_var, value=val,
                font=F_LABEL, bg=C_CARD, fg=C_TEXT,
                activebackground=C_CARD, selectcolor=C_CARD,
            ).pack(side=tk.LEFT, padx=(0, 10))

        self._bonus_btn = tk.Button(
            r2, text="Output options ▾", font=F_LABEL,
            bg=C_CARD, fg=C_ACCENT,
            activebackground=C_BORDER, activeforeground=C_ACCENT,
            relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2",
            highlightbackground=C_BORDER, highlightthickness=1,
            command=self._toggle_bonus_popover,
        )
        self._bonus_btn.pack(side=tk.LEFT)
        self._bonus_popover = None

        tk.Label(
            inner,
            text="Recommended: video < 60 min  |  < 100 frames extracted per camera"
                 "  (beyond this, panel quality degrades in the annotation app)",
            font=F_SMALL, bg=C_CARD, fg=C_TEXT2, anchor="w",
        ).pack(fill=tk.X, pady=(8, 0))

    def _toggle_bonus_popover(self):
        if self._bonus_popover and self._bonus_popover.winfo_exists():
            self._close_bonus_popover()
            return
        self._open_bonus_popover()

    def _open_bonus_popover(self):
        pop = tk.Toplevel(self, bg=C_CARD)
        pop.overrideredirect(True)
        pop.attributes('-topmost', True)
        self._bonus_popover = pop

        # Positionnement sous le bouton
        self._bonus_btn.update_idletasks()
        bx = self._bonus_btn.winfo_rootx()
        by = self._bonus_btn.winfo_rooty() + self._bonus_btn.winfo_height() + 2
        pop.geometry(f"+{bx}+{by}")

        outer = tk.Frame(pop, bg=C_BORDER, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=C_CARD, padx=14, pady=10)
        inner.pack()

        tk.Label(inner, text="OUTPUT OPTIONS", font=("Segoe UI", 8, "bold"),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor='w', pady=(0, 8))

        # Export annotations
        tk.Checkbutton(
            inner, text="Export annotations", variable=self._export_annot_var,
            font=F_LABEL, bg=C_CARD, fg=C_TEXT,
            activebackground=C_CARD, selectcolor=C_CARD,
            command=self._refresh_annot_format_state,
        ).pack(anchor='w')

        self._annot_format_frame = tk.Frame(inner, bg=C_CARD)
        self._annot_format_frame.pack(anchor='w', padx=(20, 0), pady=(2, 8))
        for label, val in [("YOLO", "yolo"), ("COCO", "coco"), ("Both", "both")]:
            tk.Radiobutton(
                self._annot_format_frame, text=label,
                variable=self._annot_format_var, value=val,
                font=F_LABEL, bg=C_CARD, fg=C_TEXT,
                activebackground=C_CARD, selectcolor=C_CARD,
            ).pack(side=tk.LEFT, padx=(0, 8))

        # HTML report
        tk.Checkbutton(
            inner, text="HTML report", variable=self._html_report_var,
            font=F_LABEL, bg=C_CARD, fg=C_TEXT,
            activebackground=C_CARD, selectcolor=C_CARD,
        ).pack(anchor='w')

        self._refresh_annot_format_state()

        # Fermeture au clic en dehors
        pop.bind('<FocusOut>', lambda e: self.after(100, self._check_popover_focus))
        pop.focus_set()

    def _close_bonus_popover(self):
        if self._bonus_popover and self._bonus_popover.winfo_exists():
            self._bonus_popover.destroy()
        self._bonus_popover = None
        self._update_bonus_btn_label()

    def _check_popover_focus(self):
        if self._bonus_popover and self._bonus_popover.winfo_exists():
            try:
                focused = self.focus_get()
                if focused and str(focused).startswith(str(self._bonus_popover)):
                    return
            except Exception:
                pass
            self._close_bonus_popover()

    def _refresh_annot_format_state(self):
        state = tk.NORMAL if self._export_annot_var.get() else tk.DISABLED
        for w in self._annot_format_frame.winfo_children():
            w.config(state=state)
        self._update_bonus_btn_label()

    def _update_bonus_btn_label(self):
        opts = []
        if self._export_annot_var.get():
            opts.append(self._annot_format_var.get().upper())
        if self._html_report_var.get():
            opts.append("HTML")
        label = f"Output options ({', '.join(opts)}) ▾" if opts else "Output options ▾"
        self._bonus_btn.config(text=label)

    def _get_current_drop_dir(self):
        if self._track_current_drop:
            d = os.path.join(PROJECT_ROOT, self._results_dir, self._track_current_drop)
            if os.path.isdir(d):
                return d
        return None

    def _get_metadata(self) -> dict:
        return {
            'campaign':   self._meta_campagne.get().strip(),
            'location':   self._meta_localisa.get().strip(),
            'site':       self._meta_site.get().strip(),
            'drop_id':    self._meta_drop_id.get().strip(),
            'date':       self._meta_date.get().strip(),
            'latitude':   self._meta_latitude.get().strip(),
            'longitude':  self._meta_longitude.get().strip(),
            'habitat':    self._meta_habitat.get().strip(),
            'visibility': self._meta_visib.get().strip(),
            'depth':      self._meta_profondeur.get().strip(),
        }

    def _build_buttons(self, parent):
        row = tk.Frame(parent, bg=C_BG)
        row.pack(pady=(0, 8))

        kw = dict(
            font=F_BTN, fg=C_CARD,
            relief=tk.FLAT, bd=0,
            padx=20, pady=8, cursor="hand2",
            activeforeground=C_CARD,
            disabledforeground="#A0AEC0",
        )

        self._btn_start_det = tk.Button(
            row, text="Start detection only",
            bg=C_BTN_SECONDARY, activebackground="#1E3A5F",
            command=self._start_detection_only, **kw
        )
        self._btn_start_det.pack(side=tk.LEFT, padx=5)

        self._btn_start_all = tk.Button(
            row, text="Start All",
            bg=C_BTN_PRIMARY, activebackground="#1A4731",
            command=self._start_all, **kw
        )
        self._btn_start_all.pack(side=tk.LEFT, padx=5)

        self._btn_stop = tk.Button(
            row, text="Stop",
            bg=C_BTN_DANGER, activebackground="#7B1C2A",
            command=self._stop, **kw
        )
        self._btn_stop.pack(side=tk.LEFT, padx=5)

        tk.Button(
            row, text="Open Results",
            bg=C_BTN_NEUTRAL, activebackground="#374151",
            command=self._open_results, **kw
        ).pack(side=tk.LEFT, padx=5)

        self._set_running(False)

    # ── Panneau de suivi ──────────────────────────────────────────────────────

    def _build_tracking_panel(self, parent):
        # Badges — informations générales
        badges_row = tk.Frame(parent, bg=C_BG)
        badges_row.pack(fill=tk.X, padx=6, pady=(6, 4))

        def make_badge(key):
            border = tk.Frame(badges_row, bg=C_BORDER)
            border.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))
            inner = tk.Frame(border, bg=C_CARD, padx=10, pady=8)
            inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
            tk.Label(inner, text=key, font=F_SMALL, bg=C_CARD, fg=C_TEXT2).pack(anchor='w')
            val = tk.Label(inner, text="—", font=F_LABEL, bg=C_CARD, fg=C_TEXT)
            val.pack(anchor='w')
            return val

        self._badge_mode_val   = make_badge("MODE")
        self._badge_ncams_val  = make_badge("CAMERAS")
        self._badge_drop_val   = make_badge("DROP")
        self._badge_statut_val = make_badge("STATUS")

        # Progression
        prog_card = tk.Frame(parent, bg=C_CARD,
                             highlightbackground=C_BORDER, highlightthickness=1)
        prog_card.pack(fill=tk.X, padx=6, pady=4)
        prog_inner = tk.Frame(prog_card, bg=C_CARD, padx=14, pady=10)
        prog_inner.pack(fill=tk.X)

        tk.Label(prog_inner, text="PROGRESS", font=("Segoe UI", 8, "bold"),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor='w', pady=(0, 6))

        self._progressbar = ttk.Progressbar(
            prog_inner, orient=tk.HORIZONTAL,
            mode='determinate', style='RENAI.Horizontal.TProgressbar',
        )
        self._progressbar.pack(fill=tk.X, pady=(0, 6))

        self._lbl_step = tk.Label(
            prog_inner, text="Waiting…",
            font=("Segoe UI", 10, "bold"), bg=C_CARD, fg=C_TEXT2, anchor="w",
        )
        self._lbl_step.pack(fill=tk.X)

        # Tableau par caméra
        cam_card = tk.Frame(parent, bg=C_CARD,
                            highlightbackground=C_BORDER, highlightthickness=1)
        cam_card.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        cam_inner = tk.Frame(cam_card, bg=C_CARD, padx=8, pady=8)
        cam_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(cam_inner, text="TRACKING BY DROP / CAMERA", font=("Segoe UI", 8, "bold"),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor='w', pady=(0, 6))

        # Split horizontal : tableau à gauche | métadonnées à droite
        split = tk.Frame(cam_inner, bg=C_CARD)
        split.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(split, bg=C_CARD)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cols = ('drop_id', 'camera', 'video', 'clap', 'extraction', 'detection', 'classification', 'csv', 'statut')
        self._tree = ttk.Treeview(tree_frame, columns=cols, show='headings',
                                  height=6, style='Track.Treeview')

        col_conf = [
            ('drop_id',        'Drop',            90, tk.W,      True),
            ('camera',         'Camera',          55, tk.CENTER, False),
            ('video',          'Video',           80, tk.W,      False),
            ('clap',           't0',              38, tk.CENTER, False),
            ('extraction',     'Extraction',      72, tk.CENTER, False),
            ('detection',      'Detection',       72, tk.CENTER, False),
            ('classification', 'Classification',  95, tk.CENTER, False),
            ('csv',            'CSV',            105, tk.CENTER, False),
            ('statut',         'Status',          95, tk.CENTER, False),
        ]
        for col, heading, width, anchor, stretch in col_conf:
            self._tree.heading(col, text=heading)
            self._tree.column(col, width=width, anchor=anchor, stretch=stretch)

        self._tree.tag_configure('row_ok',  background=C_ROW_OK)
        self._tree.tag_configure('row_err', background=C_ROW_ERR)
        self._tree.tag_configure('row_run', background=C_ROW_RUN)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind('<<TreeviewSelect>>', self._on_tree_select)

        # Panneau métadonnées (caché jusqu'à la sélection d'un drop)
        self._meta_panel = tk.Frame(split, bg=C_CARD)
        tk.Frame(self._meta_panel, bg=C_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))

        meta_outer = tk.Frame(self._meta_panel, bg=C_CARD)
        meta_outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Barre d'onglets ────────────────────────────────────────────────
        tab_bar = tk.Frame(meta_outer, bg=C_CARD)
        tab_bar.pack(fill=tk.X, padx=6, pady=(4, 0))
        self._tab_btn_meta = tk.Button(
            tab_bar, text="METADATA", font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
            command=lambda: self._switch_meta_tab('meta'),
        )
        self._tab_btn_meta.pack(side=tk.LEFT)
        self._tab_btn_video = tk.Button(
            tab_bar, text="VIDEO", font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
            command=lambda: self._switch_meta_tab('video'),
        )
        self._tab_btn_video.pack(side=tk.LEFT)
        tk.Frame(meta_outer, bg=C_BORDER, height=1).pack(fill=tk.X, padx=6)

        # ── Contenu onglet METADATA ────────────────────────────────────────
        self._meta_content = tk.Frame(meta_outer, bg=C_CARD)

        _meta_vsb = ttk.Scrollbar(self._meta_content, orient=tk.VERTICAL)
        _meta_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        _meta_canvas = tk.Canvas(self._meta_content, bg=C_CARD, highlightthickness=0,
                                 yscrollcommand=_meta_vsb.set)
        _meta_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _meta_vsb.config(command=_meta_canvas.yview)

        meta_right = tk.Frame(_meta_canvas, bg=C_CARD, padx=10)
        _win = _meta_canvas.create_window((0, 0), window=meta_right, anchor='nw')

        meta_right.bind('<Configure>',
                        lambda e: _meta_canvas.configure(
                            scrollregion=_meta_canvas.bbox('all')))
        _meta_canvas.bind('<Configure>',
                          lambda e: _meta_canvas.itemconfig(_win, width=e.width))

        def _on_meta_wheel(e):
            _meta_canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        _meta_canvas.bind('<MouseWheel>', _on_meta_wheel)
        meta_right.bind('<MouseWheel>', _on_meta_wheel)

        meta_grid = tk.Frame(meta_right, bg=C_CARD)
        meta_grid.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        for i, (lbl_text, var) in enumerate([
            ("Campaign",   self._meta_campagne),
            ("Location",   self._meta_localisa),
            ("Site",       self._meta_site),
            ("Drop ID",    self._meta_drop_id),
            ("Date",       self._meta_date),
            ("Latitude",   self._meta_latitude),
            ("Longitude",  self._meta_longitude),
            ("Habitat",    self._meta_habitat),
            ("Visibility", self._meta_visib),
            ("Depth",      self._meta_profondeur),
        ]):
            r, c = divmod(i, 2)
            cell = tk.Frame(meta_grid, bg=C_CARD)
            cell.grid(row=r, column=c, sticky='ew', padx=(0 if c == 0 else 6, 0), pady=(0, 4))
            lbl = tk.Label(cell, text=lbl_text, font=F_SMALL, bg=C_CARD, fg=C_TEXT2)
            lbl.pack(anchor='w')
            lbl.bind('<MouseWheel>', _on_meta_wheel)
            ef = tk.Frame(cell, bg=C_BORDER, padx=1, pady=1)
            ef.pack(fill=tk.X)
            entry = tk.Entry(ef, textvariable=var, font=F_LABEL, relief=tk.FLAT,
                             bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT)
            entry.pack(fill=tk.X, ipady=3, padx=3)
            entry.bind('<MouseWheel>', _on_meta_wheel)
            if var is self._meta_date:
                _ph = tk.Label(ef, text='YYYY-MM-DD', font=F_LABEL,
                               fg='#A0AEC0', bg=C_CARD, anchor='w', cursor='xterm')
                _ph.place(in_=entry, relx=0, rely=0, relwidth=1, relheight=1, x=4)
                _ph.bind('<Button-1>', lambda e, en=entry: en.focus_set())
                def _upd_ph(*a, ph=_ph, v=var, en=entry):
                    if v.get():
                        ph.place_forget()
                    else:
                        ph.place(in_=en, relx=0, rely=0, relwidth=1, relheight=1, x=4)
                var.trace_add('write', _upd_ph)
                entry.bind('<FocusIn>',  lambda e, ph=_ph: ph.place_forget())
                entry.bind('<FocusOut>', lambda e, fn=_upd_ph: fn())

        meta_grid.columnconfigure(0, weight=1)
        meta_grid.columnconfigure(1, weight=1)

        tk.Button(
            meta_right, text="Validate", font=F_LABEL,
            bg=C_BTN_PRIMARY, fg=C_CARD,
            activebackground="#1A4731", activeforeground=C_CARD,
            relief=tk.FLAT, bd=0, padx=14, pady=5, cursor="hand2",
            command=self._validate_drop_meta,
        ).pack(anchor='e', pady=(8, 2))

        # ── Contenu onglet VIDEO ───────────────────────────────────────────
        self._video_content = tk.Frame(meta_outer, bg=C_CARD, padx=10)

        tk.Label(self._video_content,
                 text="Click a camera row to load video info",
                 font=F_SMALL, bg=C_CARD, fg=C_TEXT2, anchor='w',
                 ).pack(anchor='w', pady=(6, 8))

        vid_grid = tk.Frame(self._video_content, bg=C_CARD)
        vid_grid.pack(fill=tk.X)

        for _i, (_lbl, _var) in enumerate([
            ("Format",      self._vid_format),
            ("Duration",    self._vid_duration),
            ("Resolution",  self._vid_resolution),
            ("FPS",         self._vid_fps),
            ("Codec",       self._vid_codec),
            ("File size",   self._vid_size),
        ]):
            _r, _c = divmod(_i, 2)
            _cell = tk.Frame(vid_grid, bg=C_CARD)
            _cell.grid(row=_r, column=_c, sticky='ew',
                       padx=(0 if _c == 0 else 6, 0), pady=(0, 6))
            tk.Label(_cell, text=_lbl, font=F_SMALL, bg=C_CARD, fg=C_TEXT2).pack(anchor='w')
            tk.Label(_cell, textvariable=_var, font=F_LABEL,
                     bg=C_CARD, fg=C_TEXT, anchor='w').pack(anchor='w')

        vid_grid.columnconfigure(0, weight=1)
        vid_grid.columnconfigure(1, weight=1)

        # Onglet METADATA actif par défaut
        self._switch_meta_tab('meta')

        # Dernier événement
        self._evt_card = tk.Frame(parent, bg=C_CARD,
                                  highlightbackground=C_BORDER, highlightthickness=1)
        self._evt_card.pack(fill=tk.X, padx=6, pady=(4, 6))
        evt_card = self._evt_card
        evt_inner = tk.Frame(evt_card, bg=C_CARD, padx=14, pady=8)
        evt_inner.pack(fill=tk.X)

        tk.Label(evt_inner, text="LAST EVENT", font=("Segoe UI", 8, "bold"),
                 bg=C_CARD, fg=C_TEXT2).pack(anchor='w', pady=(0, 4))

        self._lbl_last_event = tk.Label(
            evt_inner, text="—", font=("Consolas", 9),
            bg=C_CARD, fg=C_TEXT2, anchor="w",
        )
        self._lbl_last_event.pack(fill=tk.X)

    def _get_csv_status(self, meta: dict = None, validated: bool = False) -> str:
        if self._csv_mode_var.get() == 'minimum':
            if meta and meta.get('drop_id') and meta.get('date'):
                return '✅ Complete'
            if validated:
                return '🟧 Validated'
            return '⚠️ Incomplete'
        if meta and all(str(meta.get(f, '')).strip() for f in _FULL_META_FIELDS):
            return '✅ Complete'
        if validated:
            return '🟧 Validated'
        return '⚠️ Incomplete'

    def _on_tree_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            self._meta_panel.pack_forget()
            return
        iid = sel[0]
        drop_name = iid if '::' not in iid else iid.split('::')[0]
        if drop_name not in self._track_drops:
            self._meta_panel.pack_forget()
            return

        self._form_current_drop = drop_name
        meta = self._track_drops[drop_name].get('meta', {})

        self._form_updating = True
        self._meta_campagne.set(  meta.get('campaign',   ''))
        self._meta_localisa.set(  meta.get('location',   ''))
        self._meta_site.set(      meta.get('site',       ''))
        self._meta_drop_id.set(   meta.get('drop_id',   ''))
        self._meta_date.set(      meta.get('date',       ''))
        self._meta_latitude.set(  meta.get('latitude',   ''))
        self._meta_longitude.set( meta.get('longitude',  ''))
        self._meta_habitat.set(   meta.get('habitat',    ''))
        self._meta_visib.set(     meta.get('visibility', ''))
        self._meta_profondeur.set(meta.get('depth',      ''))
        self._form_updating = False

        if '::' in iid:
            cam_data = self._track_cams.get(iid, {})
            self._load_video_meta(cam_data.get('video_path'))
        else:
            for sv in (self._vid_format, self._vid_duration, self._vid_resolution,
                       self._vid_fps, self._vid_codec, self._vid_size):
                sv.set('—')

        self._meta_panel.pack(side=tk.LEFT, fill=tk.Y)

    def _switch_meta_tab(self, tab: str):
        if tab == 'meta':
            self._video_content.pack_forget()
            self._meta_content.pack(fill=tk.BOTH, expand=True)
            self._tab_btn_meta.config(bg=C_ACCENT, fg=C_CARD,
                                      activebackground=C_ACCENT, activeforeground=C_CARD)
            self._tab_btn_video.config(bg=C_CARD, fg=C_TEXT2,
                                       activebackground=C_CARD, activeforeground=C_TEXT2)
        else:
            self._meta_content.pack_forget()
            self._video_content.pack(fill=tk.BOTH, expand=True)
            self._tab_btn_meta.config(bg=C_CARD, fg=C_TEXT2,
                                      activebackground=C_CARD, activeforeground=C_TEXT2)
            self._tab_btn_video.config(bg=C_ACCENT, fg=C_CARD,
                                       activebackground=C_ACCENT, activeforeground=C_CARD)

    def _load_video_meta(self, video_path: str | None):
        _dash = '—'
        if not video_path or not os.path.isfile(video_path):
            for sv in (self._vid_format, self._vid_duration, self._vid_resolution,
                       self._vid_fps, self._vid_codec, self._vid_size):
                sv.set(_dash)
            return
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            for sv in (self._vid_format, self._vid_duration, self._vid_resolution,
                       self._vid_fps, self._vid_codec, self._vid_size):
                sv.set(_dash)
            return
        fps        = cap.get(cv2.CAP_PROP_FPS) or 0
        n_frames   = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        width      = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        cap.release()
        codec   = ''.join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)).strip()
        dur_s   = int(n_frames / fps) if fps > 0 else 0
        dur_str = f"{dur_s // 3600:02d}:{(dur_s % 3600) // 60:02d}:{dur_s % 60:02d}"
        ext     = os.path.splitext(video_path)[1].upper().lstrip('.')
        size    = os.path.getsize(video_path)
        size_str = f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.1f} MB"
        fps_str  = f"{fps:.2f} fps" if fps != int(fps) else f"{int(fps)} fps"
        self._vid_format.set(ext or _dash)
        self._vid_duration.set(dur_str)
        self._vid_resolution.set(f"{width} × {height}" if width else _dash)
        self._vid_fps.set(fps_str if fps else _dash)
        self._vid_codec.set(codec or _dash)
        self._vid_size.set(size_str)

    def _on_meta_change(self, *args):
        if self._form_updating or not self._form_current_drop:
            return
        drop_name = self._form_current_drop
        if drop_name not in self._track_drops:
            return
        meta = {
            'campaign':   self._meta_campagne.get().strip(),
            'location':   self._meta_localisa.get().strip(),
            'site':       self._meta_site.get().strip(),
            'drop_id':    self._meta_drop_id.get().strip(),
            'date':       self._meta_date.get().strip(),
            'latitude':   self._meta_latitude.get().strip(),
            'longitude':  self._meta_longitude.get().strip(),
            'habitat':    self._meta_habitat.get().strip(),
            'visibility': self._meta_visib.get().strip(),
            'depth':      self._meta_profondeur.get().strip(),
        }
        self._track_drops[drop_name]['meta'] = meta
        self._track_drops[drop_name]['csv']  = self._get_csv_status(
            meta=meta, validated=self._track_drops[drop_name].get('validated', False)
        )
        self._refresh_drop_row(drop_name)

        if self._form_save_after:
            self.after_cancel(self._form_save_after)
        self._form_save_after = self.after(
            800, lambda dn=drop_name: self._save_drop_metadata_from_tracking(dn)
        )

    def _save_drop_metadata_from_tracking(self, drop_name: str):
        import json
        if drop_name not in self._track_drops:
            return
        drop  = self._track_drops[drop_name]
        payload = {**drop.get('meta', {}), 'validated': drop.get('validated', False)}
        meta_dir  = os.path.join(PROJECT_ROOT, self._results_dir, drop_name)
        os.makedirs(meta_dir, exist_ok=True)
        meta_path = os.path.join(meta_dir, 'drop_metadata.json')
        try:
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log(f"[WARN] Metadata save failed: {e}\n", "warn")

    def _validate_drop_meta(self):
        drop_name = self._form_current_drop
        if not drop_name or drop_name not in self._track_drops:
            return
        meta = self._track_drops[drop_name].get('meta', {})
        self._track_drops[drop_name]['validated'] = True
        self._track_drops[drop_name]['csv'] = self._get_csv_status(meta=meta, validated=True)
        self._refresh_drop_row(drop_name)
        self._save_drop_metadata_from_tracking(drop_name)

    def _reset_tracking(self, mode_key: str, mode_label: str, drop_folder: str):
        self._track_mode_key     = mode_key
        self._track_drops        = {}
        self._track_drop_order   = []
        self._track_cams         = {}
        self._track_cam_order    = []
        self._track_step_count   = 0
        self._track_current_cam  = ''

        drop_name = os.path.basename(drop_folder.rstrip('/\\'))
        self._track_current_drop = drop_name

        cameras = []
        try:
            for p in sorted(Path(drop_folder).iterdir()):
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                    cam_id = re.sub(r'\s+', '_', p.stem)
                    cameras.append((cam_id, p.name, str(p)))
        except OSError:
            pass

        drop_meta  = {}
        validated  = False
        meta_path  = os.path.join(PROJECT_ROOT, self._results_dir, drop_name, 'drop_metadata.json')
        if os.path.isfile(meta_path):
            import json
            try:
                with open(meta_path, encoding='utf-8') as f:
                    data = json.load(f)
                validated = data.pop('validated', False)
                drop_meta = data
            except Exception:
                pass

        if not drop_meta.get('drop_id'):
            drop_meta['drop_id'] = drop_name

        self._track_drops[drop_name] = {
            'csv':       self._get_csv_status(meta=drop_meta, validated=validated),
            'statut':    _S_WAIT,
            'meta':      drop_meta,
            'validated': validated,
        }
        self._track_drop_order.append(drop_name)

        for cam_id, video_name, video_path in cameras:
            key = f"{drop_name}::{cam_id}"
            self._track_cams[key] = {
                'cam_id': cam_id, 'video': video_name, 'video_path': video_path,
                'clap': '', 'extraction': '', 'detection': '', 'classification': '',
                'statut': _S_WAIT,
            }
            self._track_cam_order.append(key)

        n = len(cameras)
        self._track_step_total = (7 if mode_key == 'all' else 5) * n + 3

        self._badge_mode_val.config(text=mode_label)
        self._badge_ncams_val.config(text=str(n))
        self._badge_drop_val.config(text=drop_name)
        self._badge_statut_val.config(text=_S_RUNNING, fg=C_WARNING)
        self._progressbar['value'] = 0
        self._lbl_step.config(text="Initializing…", fg=C_TEXT2)
        self._lbl_last_event.config(text="—")

        for row in self._tree.get_children():
            self._tree.delete(row)
        for dn in self._track_drop_order:
            self._refresh_drop_row(dn)
            for key in self._track_cam_order:
                if key.startswith(f"{dn}::"):
                    self._refresh_cam_row(key)

        self._notebook.select(0)

    def _reset_tracking_for_run(self, mode_key: str, mode_label: str):
        self._track_mode_key    = mode_key
        self._track_step_count  = 0
        self._track_step_total  = (
            ((7 if mode_key == 'all' else 5) * len(self._track_cams)) + 3
        )
        self._track_current_cam  = ''
        self._track_current_drop = self._track_drop_order[0] if self._track_drop_order else ''
        self._stop_campaign.clear()

        for dn in self._track_drop_order:
            if mode_key == 'detect_only':
                self._track_drops[dn]['csv'] = '—'
            self._track_drops[dn]['statut'] = _S_WAIT
            self._refresh_drop_row(dn)
        for key in self._track_cam_order:
            self._track_cams[key].update({
                'clap': '', 'extraction': '', 'detection': '',
                'classification': '', 'statut': _S_WAIT,
            })
            self._refresh_cam_row(key)

        n_drops = len(self._track_drop_order)
        drop_label = self._track_drop_order[0] if n_drops == 1 else f"{n_drops} drops"
        self._badge_mode_val.config(text=mode_label)
        self._badge_ncams_val.config(text=str(len(self._track_cams)))
        self._badge_drop_val.config(text=drop_label)
        self._badge_statut_val.config(text=_S_RUNNING, fg=C_WARNING)
        self._progressbar['value'] = 0
        self._lbl_step.config(text="Initializing…", fg=C_TEXT2)
        self._lbl_last_event.config(text="—")
        self._notebook.select(0)

    def _refresh_drop_row(self, drop_name: str):
        d = self._track_drops.get(drop_name, {})
        values = (drop_name, '', '', '', '', '', '', d.get('csv', ''), d.get('statut', _S_WAIT))
        status = d.get('statut', _S_WAIT)
        tag = ('row_ok'  if status == _S_OK
               else 'row_err' if status == _S_ERROR
               else 'row_run' if status == _S_RUNNING
               else '')
        if self._tree.exists(drop_name):
            self._tree.item(drop_name, values=values, tags=(tag,))
        else:
            self._tree.insert('', tk.END, iid=drop_name, values=values, tags=(tag,), open=True)

    def _refresh_cam_row(self, key: str):
        d = self._track_cams.get(key, {})
        drop_name = key.split('::')[0]
        values = (
            '',
            d.get('cam_id', ''),
            d.get('video', ''),
            d.get('clap', ''),
            d.get('extraction', ''),
            d.get('detection', ''),
            d.get('classification', ''),
            '',
            d.get('statut', _S_WAIT),
        )
        status = d.get('statut', _S_WAIT)
        tag = ('row_ok'  if status == _S_OK
               else 'row_err' if status == _S_ERROR
               else 'row_run' if status == _S_RUNNING
               else '')
        if self._tree.exists(key):
            self._tree.item(key, values=values, tags=(tag,))
        else:
            parent = drop_name if self._tree.exists(drop_name) else ''
            self._tree.insert(parent, tk.END, iid=key, values=values, tags=(tag,))

    def _update_tracking(self, kind: str, text: str):
        if kind == 'done':
            # Mettre à jour le statut de chaque drop
            for dn in self._track_drop_order:
                drop_cams = {k: v for k, v in self._track_cams.items() if k.startswith(f"{dn}::")}
                if drop_cams:
                    has_err = any(d.get('statut') == _S_ERROR for d in drop_cams.values())
                    self._track_drops[dn]['statut'] = _S_ERROR if has_err else _S_OK
                    self._refresh_drop_row(dn)
            has_error = any(d.get('statut') == _S_ERROR for d in self._track_drops.values())
            self._badge_statut_val.config(
                text=_S_ERROR if has_error else _S_OK,
                fg=C_ERROR if has_error else C_SUCCESS,
            )
            self._progressbar['value'] = 100
            self._lbl_step.config(text="Pipeline complete.", fg=C_SUCCESS)
            return

        t = text.strip()
        if not t:
            return

        # [CAM] Caméra cam_id
        m = _RE_CAM.search(t)
        if m:
            cam_id = m.group(1)
            self._track_current_cam = cam_id
            key = f"{self._track_current_drop}::{cam_id}"
            if key not in self._track_cams:
                self._track_cams[key] = {
                    'cam_id': cam_id, 'video': '', 'clap': '', 'extraction': '',
                    'detection': '', 'classification': '', 'statut': _S_WAIT,
                }
                self._track_cam_order.append(key)
            self._track_cams[key]['statut'] = _S_RUNNING
            if self._track_current_drop in self._track_drops:
                self._track_drops[self._track_current_drop]['statut'] = _S_RUNNING
                self._refresh_drop_row(self._track_current_drop)
            self._refresh_cam_row(key)
            self._lbl_last_event.config(text=t[:100])
            return

        # [STEP] [N/10] label
        m = _RE_STEP_START.search(t)
        if m:
            n, lbl = int(m.group(1)), m.group(2).strip()
            self._lbl_step.config(text=f"Running step: [{n}/10] {lbl}", fg=C_ACCENT)
            self._lbl_last_event.config(text=t[:100])
            return

        # [OK] [N/10] label
        m = _RE_STEP_OK.search(t)
        if m:
            n, lbl = int(m.group(1)), m.group(2).strip()
            mc  = _RE_CAM_LABEL.search(lbl)
            cam_id = mc.group(1) if mc else None
            key    = f"{self._track_current_drop}::{cam_id}" if cam_id else None
            col    = _STEP_COL.get(n)
            if col and key and key in self._track_cams:
                if self._track_cams[key].get(col) != '❌':
                    self._track_cams[key][col] = '✅'
            if n == 7 and key and key in self._track_cams:
                self._track_cams[key]['statut'] = _S_OK
            if key:
                self._refresh_cam_row(key)
            self._track_step_count += 1
            if self._track_step_total > 0:
                pct = int(100 * self._track_step_count / self._track_step_total)
                self._progressbar['value'] = min(pct, 99)
            self._lbl_last_event.config(text=t[:100])
            return

        # [ERROR] [N/10]
        m = _RE_STEP_ERR.search(t)
        if m:
            cam_id = self._track_current_cam
            key    = f"{self._track_current_drop}::{cam_id}" if cam_id else None
            col    = _STEP_COL.get(int(m.group(1)))
            if col and key and key in self._track_cams:
                self._track_cams[key][col] = '❌'
                self._track_cams[key]['statut'] = _S_ERROR
                self._refresh_cam_row(key)
            self._badge_statut_val.config(text=_S_ERROR, fg=C_ERROR)
            self._lbl_last_event.config(text=t[:100])
            return

        if kind in ('ok', 'error', 'warn') and t:
            self._lbl_last_event.config(text=t[:100])

    # ── Console ───────────────────────────────────────────────────────────────

    def _build_console(self, parent):
        wrapper = tk.Frame(parent, bg=C_BG)
        wrapper.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self._console = scrolledtext.ScrolledText(
            wrapper, font=F_MONO,
            bg=C_CONSOLE_BG, fg=C_CONSOLE_FG,
            insertbackground=C_CARD,
            selectbackground="#264f78",
            relief=tk.FLAT, bd=0,
            padx=12, pady=10,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self._console.pack(fill=tk.BOTH, expand=True)

        for tag, color in [
            ("error", C_LOG_ERROR), ("ok",   C_LOG_OK),
            ("info",  C_LOG_INFO),  ("warn", C_LOG_WARN), ("cmd", C_LOG_CMD),
        ]:
            self._console.tag_config(tag, foreground=color)

    def _log(self, text: str, tag: str = ""):
        self._console.configure(state=tk.NORMAL)
        if tag:
            self._console.insert(tk.END, text, tag)
        else:
            self._console.insert(tk.END, text)
        self._console.see(tk.END)
        self._console.configure(state=tk.DISABLED)

    def _poll_queue(self):
        try:
            while True:
                kind, text = self._queue.get_nowait()
                if kind == "line":
                    tag = (
                        "error" if any(w in text.lower()
                                       for w in ("error", "exception", "traceback"))
                        else "warn" if "warning" in text.lower()
                        else "ok"   if any(w in text.lower()
                                          for w in ("ok", "success", "done", "100%"))
                        else ""
                    )
                    self._log(text, tag)
                elif kind in ("ok", "error", "warn", "info", "cmd"):
                    self._log(text, kind)
                elif kind == "_next_drop":
                    self._track_current_drop = text
                    self._badge_drop_val.config(text=text)
                elif kind == "done":
                    self._set_running(False)
                self._update_tracking(kind, text)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    # ── Actions des boutons ───────────────────────────────────────────────────

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Select a drop or campaign folder",
            initialdir=self._folder_var.get() or PROJECT_ROOT,
        )
        if not folder:
            return
        self._folder_var.set(folder)
        self._log(f"[INFO] Folder selected: {folder}\n", "info")
        self._scan_folder(folder)
        self._preview_tree()

    def _preview_tree(self):
        import json
        self._track_drops      = {}
        self._track_drop_order = []
        self._track_cams       = {}
        self._track_cam_order  = []
        self._form_current_drop = ''
        self._meta_panel.pack_forget()

        for drop_folder in self._discovered_drops:
            drop_name = os.path.basename(drop_folder.rstrip('/\\'))

            drop_meta = {}
            validated = False
            meta_path = os.path.join(PROJECT_ROOT, self._results_dir, drop_name, 'drop_metadata.json')
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, encoding='utf-8') as f:
                        data = json.load(f)
                    validated = data.pop('validated', False)
                    drop_meta = data
                except Exception:
                    pass

            if not drop_meta.get('drop_id'):
                drop_meta['drop_id'] = drop_name

            self._track_drops[drop_name] = {
                'csv':       self._get_csv_status(meta=drop_meta, validated=validated),
                'statut':    _S_WAIT,
                'meta':      drop_meta,
                'validated': validated,
            }
            self._track_drop_order.append(drop_name)

            try:
                for p in sorted(Path(drop_folder).iterdir()):
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                        cam_id = re.sub(r'\s+', '_', p.stem)
                        key = f"{drop_name}::{cam_id}"
                        self._track_cams[key] = {
                            'cam_id': cam_id, 'video': p.name, 'video_path': str(p),
                            'clap': '', 'extraction': '', 'detection': '',
                            'classification': '', 'statut': _S_WAIT,
                        }
                        self._track_cam_order.append(key)
            except OSError:
                pass

        for row in self._tree.get_children():
            self._tree.delete(row)
        for dn in self._track_drop_order:
            self._refresh_drop_row(dn)
            for key in self._track_cam_order:
                if key.startswith(f"{dn}::"):
                    self._refresh_cam_row(key)

        n_cams = len(self._track_cams)
        n_drops = len(self._track_drop_order)
        drop_label = (self._track_drop_order[0] if n_drops == 1
                      else f"{n_drops} drops")
        self._badge_mode_val.config(text='—')
        self._badge_ncams_val.config(text=str(n_cams))
        self._badge_drop_val.config(text=drop_label)
        self._badge_statut_val.config(text=_S_WAIT, fg=C_TEXT2)
        self._progressbar['value'] = 0
        self._lbl_step.config(text="Waiting…", fg=C_TEXT2)

        if self._track_drop_order:
            first = self._track_drop_order[0]
            self._tree.selection_set(first)
            self._tree.focus(first)
            self._on_tree_select()

    def _scan_folder(self, folder: str):
        try:
            entries = os.listdir(folder)
        except OSError as e:
            self._log(f"[ERROR] Cannot read folder: {e}\n", "error")
            return

        # Drop : vidéos directement dans le dossier
        videos = sorted(f for f in entries
                        if os.path.splitext(f)[1].lower() in VIDEO_EXTS)
        if videos:
            self._folder_mode      = 'drop'
            self._discovered_drops = [folder]
            self._log(f"[INFO] Drop detected — {len(videos)} camera(s):\n", "info")
            for v in videos:
                self._log(f"         {v}\n")
            return

        # Campagne : recherche récursive de dossiers contenant des vidéos
        drop_dirs = []
        for root, dirs, files in os.walk(folder):
            videos = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTS]
            if videos:
                drop_dirs.append((root, len(videos)))
                dirs.clear()  # ce dossier est un drop, ne pas descendre plus loin
            else:
                dirs.sort()   # parcours alphabétique

        if drop_dirs:
            self._folder_mode      = 'campaign'
            self._discovered_drops = [d for d, _ in drop_dirs]
            self._log(f"[INFO] Campaign detected — {len(drop_dirs)} drop(s):\n", "info")
            for dpath, n in drop_dirs:
                self._log(f"         {os.path.basename(dpath)}  ({n} camera(s))\n")
            return

        self._folder_mode      = 'drop'
        self._discovered_drops = [folder]
        self._log("[WARN] No video detected in this folder or its subfolders.\n", "warn")

    def _start_detection_only(self):
        self._run_pipeline(mode='detect_only', label='detection only')

    def _start_all(self):
        self._run_pipeline(mode='all', label='full pipeline')

    def _show_start_confirm(self, mode: str, label: str,
                            delay: int, interval: int, max_frames: int) -> bool:
        confirmed = [False]

        dlg = tk.Toplevel(self)
        dlg.title("Confirm start")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.attributes('-topmost', True)

        outer = tk.Frame(dlg, bg=C_CARD, padx=24, pady=20)
        outer.pack(fill=tk.BOTH, expand=True)

        tk.Label(outer, text="READY TO START?", font=("Segoe UI", 11, "bold"),
                 bg=C_CARD, fg=C_TEXT).pack(anchor='w', pady=(0, 14))

        # ── Tableau récapitulatif ─────────────────────────────────────────────
        grid = tk.Frame(outer, bg=C_CARD)
        grid.pack(fill=tk.X)

        def row(label_text, value_text, r):
            tk.Label(grid, text=label_text, font=F_LABEL, bg=C_CARD,
                     fg=C_TEXT2, anchor='w', width=16).grid(
                         row=r, column=0, sticky='w', pady=2)
            tk.Label(grid, text=value_text, font=("Segoe UI", 10, "bold"),
                     bg=C_CARD, fg=C_TEXT, anchor='w').grid(
                         row=r, column=1, sticky='w', padx=(8, 0), pady=2)

        # Mode
        mode_label = "Full pipeline" if mode == 'all' else "Detection only"
        row("Mode", mode_label, 0)

        # Drops + caméras
        n_drops = len(self._discovered_drops)
        n_cams  = len(self._track_cam_order)
        if n_drops == 1:
            dn = os.path.basename(self._discovered_drops[0].rstrip('/\\'))
            drops_val = f"{dn}  ({n_cams} cam{'s' if n_cams > 1 else ''})"
        else:
            drops_val = f"{n_drops} drops  —  {n_cams} cameras total"
        row("Drop(s)", drops_val, 1)

        # Timing
        interval_str   = f"{interval}s" if interval > 0 else "auto"
        max_frames_str = str(max_frames) if max_frames > 0 else "unlimited"
        row("Delay",      f"{delay}s", 2)
        row("Interval",   interval_str, 3)
        row("Max frames", max_frames_str, 4)

        # CSV
        row("CSV format", self._csv_mode_var.get().capitalize(), 5)

        # Bonus outputs
        bonus_parts = []
        if self._export_annot_var.get():
            bonus_parts.append(f"Annotations ({self._annot_format_var.get().upper()})")
        if self._html_report_var.get():
            bonus_parts.append("HTML report")
        row("Bonus outputs", ', '.join(bonus_parts) if bonus_parts else "—", 6)

        # ── Séparateur ────────────────────────────────────────────────────────
        tk.Frame(outer, bg=C_BORDER, height=1).pack(fill=tk.X, pady=(16, 14))

        # ── Boutons ───────────────────────────────────────────────────────────
        btn_row = tk.Frame(outer, bg=C_CARD)
        btn_row.pack(anchor='e')

        def on_cancel():
            dlg.destroy()

        def on_start():
            confirmed[0] = True
            dlg.destroy()

        tk.Button(
            btn_row, text="Cancel", font=F_LABEL,
            bg=C_CARD, fg=C_TEXT2,
            activebackground=C_BORDER, activeforeground=C_TEXT,
            relief=tk.FLAT, bd=0, padx=14, pady=5, cursor="hand2",
            highlightbackground=C_BORDER, highlightthickness=1,
            command=on_cancel,
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            btn_row, text="Start", font=("Segoe UI", 10, "bold"),
            bg=C_BTN_PRIMARY, fg=C_CARD,
            activebackground="#1A4731", activeforeground=C_CARD,
            relief=tk.FLAT, bd=0, padx=20, pady=5, cursor="hand2",
            command=on_start,
        ).pack(side=tk.LEFT)

        dlg.bind('<Return>', lambda e: on_start())
        dlg.bind('<Escape>', lambda e: on_cancel())

        # Centrage sur la fenêtre principale
        self.update_idletasks()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - dlg.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{x}+{y}")

        self.wait_window(dlg)
        return confirmed[0]

    def _run_pipeline(self, mode: str, label: str):
        if self._running:
            self._log("[WARN] Pipeline already running.\n", "warn")
            return

        folder = self._folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            self._log("[ERROR] Invalid or missing drop folder.\n", "error")
            return

        try:
            delay = int(self._delay_var.get().strip())
            if delay < 0:
                raise ValueError("delay")
        except ValueError as e:
            if "delay" in str(e):
                msg = "Delay after clap/start must be an integer >= 0."
            else:
                msg = "Delay after clap/start must be an integer >= 0."
            self._delay_entry.focus_set()
            messagebox.showerror("Invalid parameter", msg)
            return

        interval_str   = self._interval_var.get().strip()
        max_frames_str = self._max_frames_var.get().strip()

        interval   = 0
        max_frames = 0

        if interval_str:
            try:
                interval = int(interval_str)
                if interval <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Invalid parameter", "Frame interval must be an integer > 0.")
                self._interval_entry.focus_set()
                return

        if max_frames_str:
            try:
                max_frames = int(max_frames_str)
                if max_frames <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Invalid parameter", "Max frames must be an integer > 0.")
                self._max_frames_entry.focus_set()
                return

        if interval == 0 and max_frames == 0:
            messagebox.showerror(
                "Invalid parameter",
                "Set at least one of:\n• Frame interval (s)\n• Max frames",
            )
            self._interval_entry.focus_set()
            return

        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            self._log(f"[ERROR] Cannot read config.yaml: {e}\n", "error")
            return

        results_dir = os.path.join(PROJECT_ROOT, cfg.get('results_dir', 'results'))

        # ── Confirmation popup ────────────────────────────────────────────────
        if not self._show_start_confirm(mode, label, delay, interval, max_frames):
            return

        # Vérification résultats existants pour tous les drops
        existing = []
        for dp in self._discovered_drops:
            dn = os.path.basename(dp.rstrip('/\\'))
            dr = os.path.join(results_dir, dn)
            if os.path.isdir(dr) and os.listdir(dr):
                existing.append(dn)
        if existing:
            names = '\n'.join(f"  • {dn}" for dn in existing)
            confirm = messagebox.askyesno(
                "Existing results",
                f"Results already exist for:\n\n{names}\n\n"
                f"Run anyway (risk of overwriting)?",
            )
            if not confirm:
                return

        # Avertissement si des drops ont des métadonnées incomplètes
        if mode == 'all' and self._csv_mode_var.get() == 'full':
            incomplete = [
                dn for dn in self._track_drop_order
                if self._track_drops.get(dn, {}).get('csv') == '⚠️ Incomplete'
            ]
            if incomplete:
                names = '\n'.join(f"  • {dn}" for dn in incomplete)
                confirm = messagebox.askyesno(
                    "Incomplete metadata",
                    f"The following drops have incomplete metadata:\n\n{names}\n\n"
                    f"The final CSV will be generated with empty fields for these drops.\n\n"
                    f"Continue anyway?",
                )
                if not confirm:
                    return

        self._log(f"\n{'─' * 60}\n", "cmd")
        self._log(f"[START] Mode      : {label}\n", "ok")
        self._log(f"        Drops     : {len(self._discovered_drops)}\n", "info")
        interval_str_log   = f"{interval}s" if interval > 0 else "auto"
        max_frames_str_log = str(max_frames) if max_frames > 0 else "unlimited"
        self._log(f"        Delay     : {delay}s / Interval : {interval_str_log} / Max frames : {max_frames_str_log}\n", "info")
        self._log(f"{'─' * 60}\n\n", "cmd")

        self._reset_tracking_for_run(mode, label)
        self._set_running(True)

        drops    = list(self._discovered_drops)
        csv_mode = self._csv_mode_var.get()
        export_annot   = self._export_annot_var.get()
        annot_format   = self._annot_format_var.get()
        html_report    = self._html_report_var.get()
        meta_by_drop = {
            os.path.basename(dp.rstrip('/\\')): self._track_drops.get(
                os.path.basename(dp.rstrip('/\\')), {}
            ).get('meta', {})
            for dp in drops
        }

        for dp in drops:
            self._save_drop_metadata_from_tracking(os.path.basename(dp.rstrip('/\\')))

        threading.Thread(
            target=self._run_drops_thread,
            args=(drops, mode, delay, interval, max_frames, cfg, csv_mode, meta_by_drop,
                  export_annot, annot_format, html_report),
            daemon=True,
        ).start()

    def _run_drops_thread(self, drops, mode, delay, interval, max_frames, cfg, csv_mode, meta_by_drop,
                          export_annot=False, annot_format='both', html_report=False):
        from core.pipeline_runner import PipelineRunner
        res_dir = cfg.get('results_dir', 'results')

        for drop_folder in drops:
            if self._stop_campaign.is_set():
                break
            drop_name = os.path.basename(drop_folder.rstrip('/\\'))
            self._queue.put(('_next_drop', drop_name))

            runner = PipelineRunner(
                drop_path=drop_folder,
                results_dir=res_dir,
                start_delay=delay,
                frame_interval=interval,
                max_frames=max_frames,
                config=cfg,
                out_queue=self._queue,
                mode=mode,
                csv_mode=csv_mode,
                metadata=meta_by_drop.get(drop_name, {}),
                send_done=False,
                export_annotations=export_annot,
                annotation_format=annot_format,
                html_report=html_report,
            )
            self._runner = runner
            runner.run()

        if mode == 'all' and not self._stop_campaign.is_set() and len(drops) > 1:
            res_abs        = os.path.join(PROJECT_ROOT, res_dir)
            campaign_csv   = os.path.join(res_abs, 'classification_campaign.csv')
            campaign_excel = os.path.join(res_abs, 'classification_campaign.xlsx')
            self._queue.put(('info', f"\n{'─'*60}\n[CAMPAIGN] Campaign files\n{'─'*60}\n"))
            for cmd, label in [
                ([sys.executable,
                  os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_campaign_csv.py'),
                  '--results_dir', res_abs, '--output', campaign_csv],
                 "Campaign CSV"),
                ([sys.executable,
                  os.path.join(PROJECT_ROOT, 'core', 'run', 'generate_campaign_excel.py'),
                  '--campaign_csv', campaign_csv,
                  '--results_dir', res_abs, '--output', campaign_excel],
                 "Campaign Excel"),
            ]:
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding='utf-8',
                    cwd=PROJECT_ROOT, env=env,
                )
                for line in proc.stdout:
                    self._queue.put(('line', line))
                proc.wait()
                tag = 'ok' if proc.returncode == 0 else 'error'
                pfx = '[OK]' if proc.returncode == 0 else '[ERROR]'
                self._queue.put((tag, f"{pfx} {label}\n"))

        self._queue.put(('done', ''))

    def _stop(self):
        if self._running and self._runner:
            self._stop_campaign.set()
            self._runner.stop()
            self._log("\n[STOP] Pipeline stopped by user.\n", "warn")
            self._set_running(False)
            self._badge_statut_val.config(text="⛔ Stopped", fg=C_TEXT2)
        else:
            self._log("[INFO] No pipeline running.\n", "info")

    def _open_results(self):
        folder    = self._folder_var.get().strip()
        drop_name = os.path.basename(folder.rstrip("/\\")) if folder else ""
        drop_results = os.path.join(PROJECT_ROOT, self._results_dir, drop_name)
        results_dir  = os.path.join(PROJECT_ROOT, self._results_dir)

        if drop_name and os.path.isdir(drop_results):
            target = drop_results
        elif os.path.isdir(results_dir):
            target = results_dir
        else:
            self._log(f"[WARN] Results folder not found: {results_dir}\n", "warn")
            return

        self._log(f"[INFO] Opening: {target}\n", "info")
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(target)
            elif system == "Darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except Exception as e:
            self._log(f"[WARN] Cannot open folder: {e}\n"
                      f"       Path: {target}\n", "warn")

    # ── Aide / User guide ────────────────────────────────────────────────────

    def _show_help(self):
        win = tk.Toplevel(self)
        win.title("RENAI — User Guide")
        win.minsize(560, 420)
        win.configure(bg=C_BG)
        win.resizable(True, True)
        win.update_idletasks()
        px = self.winfo_rootx() + (self.winfo_width()  - 740) // 2
        py = self.winfo_rooty() + (self.winfo_height() - 640) // 2
        win.geometry(f"740x640+{px}+{py}")

        hdr = tk.Frame(win, bg=C_HEADER_BG)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="RENAI — User Guide", font=F_BRAND,
                 bg=C_HEADER_BG, fg="#FFFFFF").pack(side=tk.LEFT, padx=22, pady=12)

        frame = tk.Frame(win, bg=C_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=(12, 0))

        txt = scrolledtext.ScrolledText(
            frame, wrap=tk.WORD, font=("Segoe UI", 10),
            bg=C_CARD, fg=C_TEXT, relief=tk.FLAT,
            bd=0, padx=18, pady=14, state=tk.NORMAL,
        )
        txt.pack(fill=tk.BOTH, expand=True)

        txt.tag_configure('h1',     font=("Segoe UI", 13, "bold"), foreground=C_HEADER_BG,
                          spacing1=14, spacing3=6)
        txt.tag_configure('h2',     font=("Segoe UI", 10, "bold"), foreground=C_ACCENT,
                          spacing1=14, spacing3=2)
        txt.tag_configure('body',   font=("Segoe UI", 10), foreground=C_TEXT, spacing3=3)
        txt.tag_configure('bullet', font=("Segoe UI", 10), foreground=C_TEXT,
                          lmargin1=22, lmargin2=34, spacing3=2)
        txt.tag_configure('sub',    font=("Segoe UI", 10), foreground=C_TEXT2,
                          lmargin1=38, lmargin2=50, spacing3=2)
        txt.tag_configure('note',   font=("Segoe UI", 9, "italic"), foreground=C_TEXT2,
                          spacing3=3)
        txt.tag_configure('mono',   font=("Consolas", 9), foreground=C_TEXT2,
                          background="#F0F4F8")

        def h1(t):     txt.insert(tk.END, t + "\n", 'h1')
        def h2(t):     txt.insert(tk.END, t + "\n", 'h2')
        def body(t):   txt.insert(tk.END, t + "\n", 'body')
        def bullet(t): txt.insert(tk.END, "  •  " + t + "\n", 'bullet')
        def sub(t):    txt.insert(tk.END, "       ›  " + t + "\n", 'sub')
        def note(t):   txt.insert(tk.END, t + "\n", 'note')
        def sep():     txt.insert(tk.END, "\n")

        # ── Content ───────────────────────────────────────────────────────────

        h1("RENAI — Underwater Video Processing Pipeline")
        body(
            "RENAI automates the detection and classification of fish families from "
            "underwater video drops (DOP protocol). It processes videos frame by frame, "
            "detects fish using deep learning, classifies them by family, and generates "
            "structured Excel results."
        )
        sep()

        h2("1 — Drop folder")
        bullet("Single drop mode: select a folder that contains the video files directly "
               "(.mp4/.mov/.avi). Each video file is treated as one camera.")
        bullet("Campaign mode: select a parent folder whose subfolders are individual drops. "
               "RENAI processes them sequentially and generates a combined campaign Excel at the end.")
        note("The mode is detected automatically — if .mp4 files are found at the root level "
             "it is a single drop; if they are in subfolders it is a campaign.")
        sep()

        h2("2 — Parameters")
        body("Delay after clap/start (s)")
        bullet("Seconds to skip at the start of each video before extracting frames.")
        bullet("Default: 0 s. Set to e.g. 180 if your protocol uses a 3-minute settling period.")
        sep()
        body("Frame interval (s)")
        bullet("Extracts one frame every N seconds of video.")
        bullet("Default: 1 s. Increase to reduce the total number of frames (faster processing).")
        sep()
        body("Max frames (optional)")
        bullet("Maximum number of frames to extract per camera. Leave empty for no limit.")
        bullet("If interval is also set: extracts at the given interval and stops as soon "
               "as N frames are reached.")
        bullet("If interval is left empty: RENAI automatically calculates the interval to "
               "spread exactly N frames evenly across the available video duration.")
        note("To enable auto-interval mode, leave the interval field empty — do not enter 0.")
        note("Tip: leave interval empty and set Max frames to get a consistent observation "
             "count across drops with different video lengths.")
        sep()
        body("CSV format")
        bullet("Full — all columns (campaign, site, GPS, habitat, visibility, depth…). "
               "Recommended for scientific output.")
        bullet("Minimum — detection columns only (camera, frame, family, count, confidence). "
               "Useful for quick inspection.")
        sep()

        h2("3 — Metadata")
        body("Fill in the fields for each drop before launching the pipeline:")
        bullet("Campaign, Location, Site — survey identification")
        bullet("Drop ID, Date — drop-level identifiers")
        bullet("Latitude / Longitude — GPS coordinates in decimal degrees")
        bullet("Habitat, Visibility, Depth — field observations")
        note("Metadata is saved automatically as drop_metadata.json in results/<drop_name>/. "
             "In campaign mode, click each drop in the list to edit its metadata separately.")
        sep()

        h2("4 — Output options  (Output options ▾ button)")
        body("Export annotations — saves detection bounding boxes in standard formats:")
        sub("YOLO: one .txt file per frame + classes.txt")
        sub("COCO: a single coco_annotations.json file")
        sub("Both: YOLO and COCO simultaneously")
        sep()
        body("HTML report — generates a self-contained report.html in the results folder:")
        sub("Gallery tab: all detected crops, filterable by family and camera, "
            "with full-screen lightbox on click.")
        sub("Frames tab: all extracted frames per camera with detections overlaid; "
            "crops displayed below each frame.")
        sub("Correction mode (✎): reassign crops to a different family and export "
            "a correction ZIP (images + YOLO/COCO labels + log CSV) for model retraining.")
        sep()

        h2("5 — Running the pipeline")
        body("Start All — runs the complete 10-step pipeline:")
        bullet("Steps 1–2: clap detection (T0) + frame extraction")
        bullet("Steps 3–4: fish detection (RF-DETR Large)")
        bullet("Steps 5–6: family classification (C-RADIO v3-H embeddings → PCA → MLP)")
        bullet("Steps 7–8: CSV assembly + Excel workbook")
        bullet("Steps 9–10: annotation export + HTML report (if enabled)")
        sep()
        body("Start Detection Only — runs steps 1–6 only (no CSV/Excel/exports). "
             "Useful to inspect detections before committing to full output.")
        body("Stop — interrupts the pipeline gracefully after the current step.")
        body("Open Results — opens the results folder in Windows Explorer.")
        sep()

        h2("6 — Tracking panel")
        bullet("Each row represents one camera. Columns show progress per step: "
               "Clap · Extraction · Detection · Classification.")
        bullet("⏳ Running — step in progress")
        bullet("✅ Done — completed successfully")
        bullet("❌ Error — step failed (see Console tab for details)")
        body("The VIDEO tab (right panel) shows technical info about the selected camera's "
             "video file: format, duration, resolution, FPS, codec, file size.")
        sep()

        h2("7 — Console")
        body("Shows the raw pipeline log in real time.")
        bullet("Blue — informational messages")
        bullet("Green — success / OK")
        bullet("Orange — warnings")
        bullet("Red — errors")
        sep()

        h2("8 — Results structure")
        body("Output is saved in results/<drop_name>/:")
        bullet("{cam}_frames/                  — extracted frames (.jpg)")
        bullet("{cam}_detections/              — RF-DETR bounding box crops (.jpg)")
        bullet("{cam}_annotated/               — frames with bounding boxes drawn")
        bullet("{cam}_classifications/         — per-detection classification results (.txt)")
        bullet("csv/{cam}_classification.csv  — per-camera detection table")
        bullet("classification_drop.csv       — merged table (all cameras)")
        bullet("classification_drop.xlsx      — Excel workbook (3 sheets):")
        sub("Detections — one row per detection with all metadata")
        sub("Summary — statistics by family and by camera")
        sub("Indicators — TOFS, MeanCount per family, presence/absence")
        bullet("{cam}_annotations/             — YOLO or COCO exports (if enabled)")
        bullet("planche_verticale.png          — composite vertical grid image")
        bullet("drop_metadata.json            — user-filled metadata (campaign, GPS, habitat…)")
        bullet("metadata.json                  — grid structure descriptor")
        bullet("report.html                    — self-contained HTML report (if enabled)")
        sep()

        h2("9 — Manual Correction tab")
        body(
            "The Correction tab lets you review and correct pipeline classifications "
            "frame by frame, identify fish to species level, and regenerate all output "
            "files (CSV and Excel) with the corrections applied."
        )
        sep()
        body("Opening a drop or campaign")
        bullet("Click 'Open for correction ···' and select a drop results folder "
               "(must contain at least one {cam}_frames/ subfolder).")
        bullet("To correct an entire campaign, select the campaign folder directly — "
               "RENAI detects the structure automatically and populates the Drop selector.")
        bullet("Use the Drop selector to navigate between drops, and the Camera selector "
               "to switch between cameras. Unsaved changes prompt a confirmation.")
        bullet("When switching drops in campaign mode, a metadata summary popup appears "
               "showing the key fields of the target drop (site, date, habitat, depth…). "
               "Click 'Load drop' to proceed or 'Cancel' to stay on the current drop.")
        sep()
        body("Canvas — navigation & zoom")
        bullet("Scroll wheel: zoom in/out (×0.5 to ×6), centred on the cursor.")
        bullet("Middle-click drag: pan the image.")
        bullet("⊙ ×1 or Ctrl+0: reset zoom and pan.")
        bullet("← Prev. / Next →: go to the previous / next frame.")
        bullet("⏮ ⏭: jump to the nearest frame that has detections.")
        sep()
        body("Bounding boxes")
        bullet("Each detected fish is shown as a coloured rectangle — colour matches its family.")
        bullet("Solid border: existing detection.  Dashed border: manually added detection.")
        bullet("Red border: detection marked as false positive.  "
               "Green border: family was corrected.")
        bullet("Click a bbox to select it (highlighted in blue; matching card scrolls into "
               "view in the side panel).")
        bullet("Double-click a bbox to open a zoomable crop popup "
               "(scroll wheel to zoom, Escape to close). The popup opens on the same screen "
               "as the main window.")
        sep()
        body("Side panel")
        bullet("Family tags (top): coloured badges for all families present on the current frame.")
        bullet("Scroll wheel works over the entire side panel (labels, dropdowns, buttons).")
        bullet("Each detection card shows: family name (bold) · size badge.")
        sub("Size badge: green if ≥ 64×64 px (usable by the classifier), "
            "grey if too small.")
        sub("Left colour bar: matches the detection's family colour (red for false positives).")
        sub("Family dropdown: reassign the family — bar colour and species list update instantly.")
        sub("Species dropdown: select the species (filtered to the current family; "
            "shows all 42 species if family is 'unknown'). "
            "Selecting a species auto-fills the family and derives the genus automatically.")
        sub("Changing the family clears the species and genus fields.")
        sub("✓ Valid: mark the detection as correct (default). "
            "✗ False positive: exclude from outputs.")
        sep()
        body("Drawing a new bbox  (✎ Bbox button)")
        bullet("Click ✎ Bbox to enter draw mode (cursor becomes a crosshair).")
        bullet("Drag on the canvas to draw a rectangle, then choose a family in the dialog.")
        bullet("The new detection appears with a dashed border and status 'added'.")
        bullet("Click ✎ Bbox again to exit draw mode.")
        sep()
        body("Undo")
        bullet("Ctrl+Z or the ↩ button undoes the last action (family/species change, "
               "status change, or added bbox).")
        sep()
        body("💾 Save")
        bullet("Rewrites the camera CSV (with genus and species columns), updates the raw "
               ".txt classification files, then regenerates classification_drop.csv and "
               "classification_drop.xlsx (including a Species sheet).")
        bullet("Also regenerates classification_campaign.csv and classification_campaign.xlsx "
               "(including a Species presence matrix sheet) whenever the drop belongs to a "
               "campaign — whether you opened the campaign folder or that single drop.")
        bullet("Only detections with a known family (not 'inconnu') are written to the outputs.")
        bullet("The button turns orange when there are unsaved changes.")
        bullet("Records the correction in correction_state.json, which the Indicators sheet "
               "reports as 'n/m cameras edited' so nobody mistakes raw detections for "
               "manually validated ones.")
        bullet("Also records how many frames of each camera were actually displayed, so a "
               "camera gone through and found clean reads as '200/200 frames opened — "
               "0 correction' instead of leaving no trace at all. The same line is shown "
               "live above the image while you work.")
        note("Frames are counted as *opened*, never as *checked*: the interface knows what "
             "was displayed, which is a lower bound on the attention paid, not proof that "
             "anything was looked at. Frames reached with the 'jump to next detection' "
             "shortcuts are counted; the ones skipped over are not. And a camera is *edited*, "
             "never *reviewed* — saving happens in the middle of a review.")
        note("Of the three counters, only *added* detections push MeanCount back up: removing "
             "false positives and relabelling fix what the detector saw, not what it missed, "
             "and what it missed is where the under-count comes from.")
        note("The .txt files in {cam}_classifications/ are updated on save, so the corrections "
             "live in the pipeline's own files rather than in a side database. Re-processing "
             "the drop regenerates those files and overwrites the corrections, in both "
             "processing modes — the correction record is cleared at the same time, so the "
             "Indicators sheet never claims corrections that no longer exist. There is no way "
             "to re-run only the steps after classification from this window.")
        sep()
        body("📤 Export crops")
        bullet("Choose a destination folder (e.g. crop_retraining/).")
        bullet("All detections with status 'Valid' and size ≥ 64×64 px are exported as PNG.")
        bullet("Each crop is saved in a subfolder named after its family "
               "({dest}/{family}/{filename}.png).")
        bullet("A summary shows how many crops were exported, skipped (too small), or missing.")
        note("Exported crops can be used to fine-tune the classification model: "
             "run C-RADIO embeddings on the PNGs, then retrain PCA + MLP.")
        sep()
        body("✎ Metadata")
        bullet("Opens a popup editor with the 10 metadata fields for the current drop: "
               "Drop ID, Campaign, Location, Site, Date, Latitude, Longitude, "
               "Habitat, Visibility, Depth.")
        bullet("Click 'Save metadata' to write drop_metadata.json, then patch the "
               "metadata columns in all camera CSVs, and regenerate "
               "classification_drop.csv / .xlsx.")
        bullet("Also regenerates classification_campaign.csv / .xlsx whenever the drop "
               "belongs to a campaign.")
        note("Use this button to fill or correct metadata without having to re-run "
             "the pipeline. Changes take effect immediately on all output files.")
        sep()

        note(
            f"RENAI v{__version__}  ·  Models: RF-DETR Large (detection)  ·  C-RADIO v3-H (embeddings)"
            "  ·  MLP (classification)"
        )
        note(
            "9 families: Acanthuridae · Chaetodontidae · Haemulidae · Holocentridae · "
            "Labridae · Lutjanidae · Pomacentridae · Scaridae · Serranidae"
        )

        txt.config(state=tk.DISABLED)

        btn_frame = tk.Frame(win, bg=C_BG)
        btn_frame.pack(fill=tk.X, padx=18, pady=12)
        tk.Button(
            btn_frame, text="Close", font=F_BTN,
            bg=C_ACCENT, fg="#FFFFFF",
            activebackground=C_HEADER_BG, activeforeground="#FFFFFF",
            relief=tk.FLAT, bd=0, padx=24, pady=6, cursor="hand2",
            command=win.destroy,
        ).pack(side=tk.RIGHT)

    # ── État des boutons ─────────────────────────────────────────────────────

    def _set_running(self, running: bool):
        self._running = running
        if running:
            self._btn_start_det.config(state=tk.DISABLED, bg="#1B3A6B")
            self._btn_start_all.config(state=tk.DISABLED, bg="#1A4731")
            self._btn_stop.config(state=tk.NORMAL, bg=C_BTN_DANGER)
        else:
            self._btn_start_det.config(state=tk.NORMAL, bg=C_BTN_SECONDARY)
            self._btn_start_all.config(state=tk.NORMAL, bg=C_BTN_PRIMARY)
            self._btn_stop.config(state=tk.DISABLED, bg="#6B1520")


# ── Point d'entrée ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = RenaiApp()
    app.mainloop()
