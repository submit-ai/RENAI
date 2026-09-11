"""
pipeline_runner.py — Replaces Snakemake for Windows.

Runs the 10 pipeline steps sequentially,
streaming output to a tkinter queue.

Mode 'all'          : 10 full steps (detection + classification + panel)
Mode 'detect_only'  : steps 1-4 + 7-10 (without classification)
"""

import os
import re
import sys
import queue
import threading
import subprocess
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON       = sys.executable
VIDEO_EXTS   = {'.mp4', '.mov', '.avi', '.mkv'}

sys.path.insert(0, os.path.join(PROJECT_ROOT, 'core', 'run'))
import correction_state


def _discover_cameras(drop_path: str) -> list:
    seen, result = {}, []
    for p in sorted(Path(drop_path).glob('*')):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTS:
            continue
        cam_id = re.sub(r'\s+', '_', p.stem)
        if cam_id in seen:
            cam_id = f"{cam_id}_{p.suffix.lstrip('.').lower()}"
        seen[cam_id] = str(p)
        result.append({'cam_id': cam_id, 'video_path': str(p)})
    return result


class PipelineRunner:

    def __init__(self, drop_path: str, results_dir: str,
                 start_delay: int, frame_interval: int,
                 config: dict, out_queue: queue.Queue,
                 mode: str = 'all', csv_mode: str = 'full', metadata: dict = None,
                 send_done: bool = True, max_frames: int = 0,
                 export_annotations: bool = False, annotation_format: str = 'both',
                 html_report: bool = False):
        self.drop_path      = os.path.abspath(drop_path)
        self.results_dir    = results_dir
        self.start_delay    = start_delay
        self.frame_interval = frame_interval
        self.max_frames     = max_frames
        self.config         = config
        self.out_queue      = out_queue
        self.mode           = mode
        self.csv_mode       = csv_mode
        self.metadata       = metadata or {}
        self.send_done      = send_done
        self.export_annotations  = export_annotations
        self.annotation_format   = annotation_format
        self.html_report         = html_report
        self._stop_event    = threading.Event()
        self._proc_lock     = threading.Lock()
        self._current_proc  = None

    def stop(self):
        self._stop_event.set()
        with self._proc_lock:
            if self._current_proc and self._current_proc.poll() is None:
                self._current_proc.terminate()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str = ''):
        self.out_queue.put((tag or 'line', text))

    def _run_step(self, cmd: list, label: str) -> bool:
        if self._stop_event.is_set():
            return False

        self._log(f"\n[STEP] {label}\n", 'info')
        self._log(f"       {' '.join(str(a) for a in cmd)}\n", 'cmd')

        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                encoding='utf-8',
                cwd=PROJECT_ROOT,
                env=env,
            )
            with self._proc_lock:
                self._current_proc = proc

            for line in proc.stdout:
                if self._stop_event.is_set():
                    proc.terminate()
                    return False
                tag = (
                    'error' if any(w in line.lower() for w in ('error', 'exception', 'traceback'))
                    else 'warn' if 'warning' in line.lower()
                    else 'ok'   if any(w in line.lower() for w in ('ok', 'success', 'done', '100%'))
                    else ''
                )
                self.out_queue.put((tag or 'line', line))

            proc.wait()
            if proc.returncode != 0:
                self._log(f"[ERROR] {label} — code {proc.returncode}\n", 'error')
                return False

            self._log(f"[OK] {label}\n", 'ok')
            return True

        except FileNotFoundError as e:
            self._log(f"[ERROR] Script not found: {e}\n", 'error')
            return False
        except Exception as e:
            self._log(f"[ERROR] {label} : {e}\n", 'error')
            return False

    def _script(self, *parts) -> str:
        return os.path.join(PROJECT_ROOT, *parts)

    def _model(self, key: str) -> str:
        return os.path.join(PROJECT_ROOT, self.config.get(key, ''))

    # ── Main pipeline ─────────────────────────────────────────────────────────

    def run(self):
        cfg          = self.config
        drop_name    = os.path.basename(self.drop_path.rstrip('/\\'))
        drop_results = os.path.join(PROJECT_ROOT, self.results_dir, drop_name)
        os.makedirs(drop_results, exist_ok=True)

        # Reprocessing overwrites the camera CSVs and the classification .txt
        # files, so any previous manual correction is void — drop its trace
        # rather than let the Indicators sheet claim corrections that no longer
        # exist.
        if not correction_state.clear(drop_results):
            self._log(
                f"[WARN] Could not remove {correction_state.FILENAME} from "
                f"{drop_name}: the Indicators sheet will report manual "
                f"corrections that this run has just overwritten.\n", 'warn')

        cameras = _discover_cameras(self.drop_path)
        if not cameras:
            self._log(f"[ERROR] No video found in {self.drop_path}\n", 'error')
            if self.send_done: self.out_queue.put(('done', ''))
            return

        cam_ids = [c['cam_id'] for c in cameras]
        self._log(
            f"[INFO] Drop: {drop_name} — {len(cameras)} camera(s): {', '.join(cam_ids)}\n",
            'info',
        )

        # ── Per-camera loop ───────────────────────────────────────────────────
        for cam in cameras:
            cam_id    = cam['cam_id']
            video     = cam['video_path']
            clap_json = os.path.join(drop_results, f"{cam_id}_clap.json")
            frame_dir = os.path.join(drop_results, f"{cam_id}_frames")
            det_dir   = os.path.join(drop_results, f"{cam_id}_detections")
            ann_dir   = os.path.join(drop_results, f"{cam_id}_annotated")
            cls_dir   = os.path.join(drop_results, f"{cam_id}_classifications")
            csv_file  = os.path.join(drop_results, 'csv', f"{cam_id}_classification.csv")

            self._log(f"\n{'─'*60}\n[CAM] Camera {cam_id}\n{'─'*60}\n", 'cmd')

            # 1 — Clap
            if not self._run_step([
                PYTHON, self._script('core', 'run', 'detect_clap.py'),
                '--video',     video,
                '--output',    clap_json,
                '--threshold', str(cfg.get('clap_threshold', 5.0)),
            ], f"[1/10] Clap — cam {cam_id}"):
                if self.send_done:
                    self.out_queue.put(('done', ''))
                return

            # 2 — Frames
            if not self._run_step([
                PYTHON, self._script('core', 'run', 'extract_frames.py'),
                '--video',       video,
                '--clap',        clap_json,
                '--output',      frame_dir,
                '--interval',    str(self.frame_interval),
                '--start_delay', str(self.start_delay),
                '--max_frames',  str(self.max_frames),
            ], f"[2/10] Frames — cam {cam_id}"):
                if self.send_done:
                    self.out_queue.put(('done', ''))
                return

            # 3 — Detection & crop
            if not self._run_step([
                PYTHON, self._script('core', 'run', 'detect_and_crop.py'),
                '--input',      frame_dir,
                '--output',     det_dir,
                '--threshold',  str(cfg.get('detection_threshold', 0.3)),
                '--model_path', self._model('detector_model'),
            ], f"[3/10] Detection — cam {cam_id}"):
                if self.send_done:
                    self.out_queue.put(('done', ''))
                return

            # 4 — Annotation
            if not self._run_step([
                PYTHON, self._script('core', 'run', 'annotate_frames.py'),
                '--frames',     frame_dir,
                '--detections', det_dir,
                '--output',     ann_dir,
            ], f"[4/10] Annotation — cam {cam_id}"):
                if self.send_done:
                    self.out_queue.put(('done', ''))
                return

            if self.mode == 'all':
                # 5 — Classification
                if not self._run_step([
                    PYTHON, self._script('core', 'run', 'classify_per_detection.py'),
                    '--detections',  det_dir,
                    '--output',      cls_dir,
                    '--model_path',  self._model('classifier_model'),
                    '--radio_model', cfg.get('radio_model', 'nvidia/C-RADIOv3-H'),
                    '--min_surface', str(cfg.get('min_surface', 4000)),
                    '--min_dim',     str(cfg.get('min_dim', 64)),
                ], f"[5/10] Classification — cam {cam_id}"):
                    if self.send_done:
                        self.out_queue.put(('done', ''))
                    return

                # [+] Annotation export (optional)
                if self.export_annotations:
                    ann_dir = os.path.join(drop_results, f"{cam_id}_annotations")
                    self._run_step([
                        PYTHON, self._script('core', 'export', 'export_annotations.py'),
                        '--frames_dir',          frame_dir,
                        '--detections_dir',      det_dir,
                        '--classifications_dir', cls_dir,
                        '--output_dir',          ann_dir,
                        '--format',              self.annotation_format,
                        '--cam_id',              cam_id,
                    ], f"[+] Annotation export ({self.annotation_format}) — cam {cam_id}")

                # 6 — CSV
                meta = self.metadata
                cmd6 = [
                    PYTHON, self._script('core', 'run', 'generate_final_csv.py'),
                    '--frames',          frame_dir,
                    '--classifications', cls_dir,
                    '--clap',            clap_json,
                    '--output',          csv_file,
                    '--frame_interval',  str(self.frame_interval),
                    '--start_delay',     str(self.start_delay),
                    '--cam_id',          cam_id,
                    '--csv_mode',        self.csv_mode,
                    '--campaign',        meta.get('campaign',   ''),
                    '--location',        meta.get('location',   ''),
                    '--site',            meta.get('site',       ''),
                    '--latitude',        meta.get('latitude',   ''),
                    '--longitude',       meta.get('longitude',  ''),
                    '--drop_id',         meta.get('drop_id',    drop_name),
                    '--date',            meta.get('date',       ''),
                    '--habitat',         meta.get('habitat',    ''),
                    '--visibility',      meta.get('visibility', ''),
                    '--depth',           meta.get('depth',      ''),
                ]
                if not self._run_step(cmd6, f"[6/10] CSV — cam {cam_id}"):
                    if self.send_done:
                        self.out_queue.put(('done', ''))
                    return

            # 7 — Renaming
            if not self._run_step([
                PYTHON, self._script('core', 'export', 'rename_annotated.py'),
                '--cam_id',         cam_id,
                '--drop_name',      drop_name,
                '--results_dir',    os.path.join(PROJECT_ROOT, self.results_dir),
                '--frame_interval', str(self.frame_interval),
                '--start_delay',    str(self.start_delay),
            ], f"[7/10] Renaming — cam {cam_id}"):
                if self.send_done:
                    self.out_queue.put(('done', ''))
                return

        # ── Drop CSV (all cameras combined) ───────────────────────────────────
        if self.mode == 'all':
            drop_csv  = os.path.join(drop_results, 'classification_drop.csv')
            excel_out = os.path.join(drop_results, 'classification_drop.xlsx')
            self._run_step([
                PYTHON, self._script('core', 'run', 'generate_drop_csv.py'),
                '--drop_results', drop_results,
                '--output',       drop_csv,
            ], "[+] Drop CSV — all cameras")
            self._run_step([
                PYTHON, self._script('core', 'run', 'generate_excel.py'),
                '--input',    drop_csv,
                '--output',   excel_out,
                '--drop_dir', drop_results,
            ], "[+] Excel — all cameras")

        # [+] HTML report (optional, drop-level)
        if self.mode == 'all' and self.html_report:
            self._run_step([
                PYTHON, self._script('core', 'output', 'generate_html_report.py'),
                '--drop_results', drop_results,
                '--drop_name',    drop_name,
            ], "[+] HTML report")

        # ── Global steps ──────────────────────────────────────────────────────
        planche_png = os.path.join(drop_results, 'planche_verticale.png')
        metadata    = os.path.join(drop_results, 'metadata.json')

        self._log(f"\n{'─'*60}\n[GLOBAL] Multi-camera assembly\n{'─'*60}\n", 'cmd')

        # 8 — Panel
        if not self._run_step([
            PYTHON, self._script('core', 'output', 'make_planche.py'),
            drop_name,
            '--results', os.path.join(PROJECT_ROOT, self.results_dir),
            '--output',  planche_png,
        ], "[8/10] Vertical panel"):
            if self.send_done:
                self.out_queue.put(('done', ''))
            return

        # 9 — Metadata
        if not self._run_step([
            PYTHON, self._script('core', 'output', 'make_metadata.py'),
            drop_name,
            '--results', os.path.join(PROJECT_ROOT, self.results_dir),
            '--output',  metadata,
            '--png',     planche_png,
        ], "[9/10] JSON metadata"):
            if self.send_done:
                self.out_queue.put(('done', ''))
            return

        # 10 — Validation
        ok = self._run_step([
            PYTHON, self._script('core', 'output', 'validate_planche.py'),
            planche_png,
            metadata,
        ], "[10/10] Panel validation")

        if ok:
            self.out_queue.put(('ok', "\n[OK] Pipeline completed successfully.\n"))
        else:
            self.out_queue.put(('error', "\n[ERROR] Pipeline completed with errors.\n"))

        if self.send_done: self.out_queue.put(('done', ''))
