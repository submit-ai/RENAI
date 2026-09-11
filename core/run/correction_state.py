"""Manual-correction state of a drop — written by the Manual Correction tab,
read by the Excel generators to stamp the Indicators sheets.

Why this exists: MeanCount and TOFS are recomputed from whatever the CSVs hold
at that moment, whether those rows come straight from the detector or from a
human review, and nothing in the workbook used to say which. A drop whose
cameras are only partly corrected is the worst case — its indicators are
neither raw nor corrected, and that was entirely silent.

Only what can be known for sure is recorded, and the wording never claims more
than that:

  - a camera is "edited", never "reviewed" — saving happens in the middle of a
    review, and a camera with no recorded edit may well have been read from end
    to end and found clean;
  - frames are "opened", never "checked" — the interface knows which frames were
    displayed, which is a lower bound on attention, not proof that anything was
    looked at. Frames reached by the "jump to next detection" shortcuts are
    counted, the ones skipped over are not.

Frame coverage is what makes a careful reviewer visible at all: a camera shown
as `200/200 frames opened — 0 correction` was gone through, whereas the same
camera with `12/200 frames opened` clearly was not. Nothing here says whether
the reviewer was *right*; that question needs a validation study, not a stamp.

Counts are rebuilt from durable evidence at each save rather than accumulated
blindly, so saving twice never inflates them:
  - removed    → detections currently flagged 'fp' (kept in the .txt files)
  - added      → detections with no crop file (kept in the manual sidecar JSON)
  - relabelled → detections whose family still differs from the automatic one.
                 The .txt is overwritten on save, so the original family is kept
                 here, per detection: a label put back to its automatic value
                 stops being counted, and a relabelled detection later flagged
                 'fp' is counted once, as removed.

Denominators (cameras in the drop, frames in a camera) are frozen here at save
time instead of being recounted from disk on every read. Deleting the heavy
`{cam}_frames/` folders to reclaim space would otherwise shrink them silently —
and shrinking the camera count is exactly what would hide the "mixed basis"
warning in the one case it matters.
"""

import json
import os
import sys
from datetime import datetime

FILENAME = 'correction_state.json'

_NONE_STATUS = "none — fully automatic output, uncalibrated"

_BANNER = (
    "⚠ Automatic detections under-count small and schooling taxa. "
    "MeanCount and TOFS are not directly comparable to manual counts. "
    "— Limitation of RENAI v{version}"
)


def _version():
    try:
        root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from core.version import __version__
        return __version__
    except Exception:
        return "unknown"


def banner():
    """Reliability warning shown on top of every Indicators sheet."""
    return _BANNER.format(version=_version())


def path_for(drop_dir):
    return os.path.join(str(drop_dir), FILENAME)


def load(drop_dir):
    try:
        with open(path_for(drop_dir), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clear(drop_dir):
    """Drop the state — the pipeline calls this when it reprocesses a drop,
    since that overwrites the camera CSVs and voids any previous correction."""
    try:
        p = path_for(drop_dir)
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


def _save(drop_dir, data):
    """Écrit l'état ; renvoie False si l'écriture a échoué.

    L'appelant a besoin de le savoir : un échec silencieux ici donne un onglet
    Indicators qui annonce « fully automatic output » alors que le drop vient
    d'être corrigé.
    """
    try:
        with open(path_for(drop_dir), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False


def _merge_originals(stored, current, fp_ids):
    """Automatic family of every detection that is still relabelled.

    `stored`  : {det_id: automatic family} from previous sessions
    `current` : {det_id: (family now, family read from the .txt at load)}
    `fp_ids`  : detections flagged as false positives in this save

    A detection whose family is back to its automatic value leaves the map, so
    the count stays net. A detection flagged 'fp' leaves it too, so it is never
    counted both as relabelled and as removed.
    """
    out = dict(stored)
    for det_id in fp_ids:
        out.pop(det_id, None)
    for det_id, (family_now, family_at_load) in current.items():
        if det_id in fp_ids:
            continue
        automatic = out.get(det_id, family_at_load)
        if family_now != automatic:
            out[det_id] = automatic
        else:
            out.pop(det_id, None)
    return out


def record_camera(drop_dir, cam_id, fp_ids, added, relabel_candidates,
                  frames_seen=(), frames_total=0, cameras_total=0):
    """Store what is known about one camera after a save.

    `fp_ids`             : ids of detections flagged as false positives
    `added`              : number of manually added detections
    `relabel_candidates` : {det_id: (family now, family read at load)}
    `frames_seen`        : ids of the frames displayed so far in this camera
    """
    data  = load(drop_dir)
    cams  = data.setdefault('cameras', {})
    entry = cams.setdefault(str(cam_id), {})

    fp_ids = set(fp_ids)
    entry['originals'] = _merge_originals(
        entry.get('originals', {}) or {}, relabel_candidates or {}, fp_ids)
    entry['removed'] = len(fp_ids)
    entry['added']   = int(added)

    seen = set(entry.get('frames_seen', []) or []) | set(frames_seen or ())
    entry['frames_seen'] = sorted(seen)
    if frames_total:
        entry['frames_total'] = int(frames_total)
    entry['last_edit'] = datetime.now().strftime('%Y-%m-%d %H:%M')

    if cameras_total:
        data['cameras_total'] = int(cameras_total)

    return _save(drop_dir, data)


def record_coverage(drop_dir, cam_id, frames_seen, frames_total=0,
                    cameras_total=0):
    """Persist frame coverage for a camera that was opened but not edited.

    Without this, a camera read end to end and found clean would leave no trace
    at all — the very case the coverage figure exists to make visible. No
    `last_edit` is written: nothing was changed.
    """
    if not frames_seen or not drop_dir or not os.path.isdir(str(drop_dir)):
        return
    data  = load(drop_dir)
    cams  = data.setdefault('cameras', {})
    entry = cams.setdefault(str(cam_id), {})
    seen  = set(entry.get('frames_seen', []) or []) | set(frames_seen)
    if len(seen) == len(entry.get('frames_seen', []) or []):
        return
    entry['frames_seen'] = sorted(seen)
    if frames_total:
        entry['frames_total'] = int(frames_total)
    if cameras_total:
        data['cameras_total'] = int(cameras_total)
    return _save(drop_dir, data)


def count_frames_on_disk(drop_dir, cam_id):
    """Frames of a camera that was never opened — the only case where we still
    have to ask the disk, since nothing was ever frozen for it."""
    try:
        d = os.path.join(str(drop_dir), f'{cam_id}_frames')
        return len([e for e in os.listdir(d) if e.lower().endswith('.jpg')])
    except OSError:
        return 0


def camera_ids(drop_dir):
    try:
        return sorted(e[:-len('_frames')] for e in os.listdir(str(drop_dir))
                      if e.endswith('_frames')
                      and os.path.isdir(os.path.join(str(drop_dir), e)))
    except OSError:
        return []


def count_cameras(drop_dir, data=None):
    """Cameras in the drop, preferring the total frozen at save time."""
    data = load(drop_dir) if data is None else data
    frozen = int(data.get('cameras_total', 0) or 0)
    return max(frozen, len(camera_ids(drop_dir)))


def _is_drop_dir(path):
    return os.path.isfile(os.path.join(path, 'classification_drop.csv'))


def _entry_totals(entry):
    removed    = int(entry.get('removed', 0) or 0)
    added      = int(entry.get('added', 0) or 0)
    relabelled = len(entry.get('originals', {}) or {})
    return removed, added, relabelled


def _totals(data):
    removed = added = relabelled = 0
    last = ''
    for entry in data.get('cameras', {}).values():
        r, a, rl = _entry_totals(entry)
        removed    += r
        added      += a
        relabelled += rl
        last = max(last, str(entry.get('last_edit', '')))
    return removed, added, relabelled, last


def frame_coverage(drop_dir, data=None):
    """(frames opened, frames in the drop) — frozen totals first, disk only for
    the cameras that were never opened."""
    data = load(drop_dir) if data is None else data
    cams = data.get('cameras', {})
    seen = total = 0
    for entry in cams.values():
        seen  += len(entry.get('frames_seen', []) or [])
        total += int(entry.get('frames_total', 0) or 0)
    for cam_id in camera_ids(drop_dir):
        if cam_id not in cams:
            total += count_frames_on_disk(drop_dir, cam_id)
    return seen, total


def _describe(removed, relabelled, added):
    total = removed + relabelled + added
    return (f"{total} correction{'s' if total != 1 else ''} "
            f"({removed} removed, {relabelled} relabelled, {added} added)")


def _coverage_phrase(seen, total):
    return f"{seen}/{total} frames opened" if total else None


def _edited_cameras(cams):
    return len([e for e in cams.values() if any(_entry_totals(e))])


def drop_summary(drop_dir):
    """(status, warning) for one drop's Indicators sheet."""
    if not drop_dir or not os.path.isdir(str(drop_dir)):
        return None, None
    data = load(drop_dir)
    cams = data.get('cameras', {})
    if not cams:
        return _NONE_STATUS, None

    removed, added, relabelled, last = _totals(data)
    edited     = _edited_cameras(cams)
    total_cams = count_cameras(drop_dir, data) or len(cams)
    seen, total_frames = frame_coverage(drop_dir, data)
    coverage = _coverage_phrase(seen, total_frames)

    if edited == 0:
        # Opened, gone through, nothing changed: worth saying explicitly,
        # otherwise this reads exactly like an untouched drop.
        if coverage:
            return f"none — 0 correction after {coverage}", None
        return _NONE_STATUS, None

    parts = [f"{edited}/{total_cams} cameras edited"]
    if coverage:
        parts.append(coverage)
    status = (f"{', '.join(parts)} — "
              f"{_describe(removed, relabelled, added)}, last edit {last}")
    warning = ("Edited and unedited cameras are pooled into the same indicators."
               if edited < total_cams else None)
    return status, warning


def campaign_summary(results_dir):
    """(status, warning) for the campaign Indicators sheet."""
    if not results_dir or not os.path.isdir(str(results_dir)):
        return None, None
    try:
        drops = [e for e in sorted(os.listdir(str(results_dir)))
                 if os.path.isdir(os.path.join(str(results_dir), e))
                 and _is_drop_dir(os.path.join(str(results_dir), e))]
    except OSError:
        return None, None
    if not drops:
        return None, None

    removed = added = relabelled = 0
    seen = total_frames = 0
    last, edited_drops = '', 0
    for name in drops:
        drop_dir = os.path.join(str(results_dir), name)
        data = load(drop_dir)
        s, t = frame_coverage(drop_dir, data)
        seen         += s
        total_frames += t
        if not data.get('cameras'):
            continue
        r, a, rl, l = _totals(data)
        if r or a or rl:
            edited_drops += 1
            last = max(last, l)
        removed    += r
        added      += a
        relabelled += rl

    coverage = _coverage_phrase(seen, total_frames)
    if edited_drops == 0:
        if seen and coverage:
            return f"none — 0 correction after {coverage}", None
        return _NONE_STATUS, None

    parts = [f"{edited_drops}/{len(drops)} drops contain manual corrections"]
    if coverage:
        parts.append(coverage)
    status = (f"{', '.join(parts)} — "
              f"{_describe(removed, relabelled, added)} in total, last edit {last}")
    warning = ("Corrected and uncorrected drops are pooled into the same indicators."
               if edited_drops < len(drops) else None)
    return status, warning


def tab_summary(drop_dir, cam_id=None, frames_seen=None, frames_total=0):
    """Short one-line status for the Manual Correction tab.

    Same vocabulary as the workbooks, without the breakdown: whoever is
    correcting sees, live, what the output will claim about their work.
    `frames_seen` / `frames_total` describe the camera currently open, so the
    line reacts as soon as someone navigates, before any save.
    """
    if not drop_dir or not os.path.isdir(str(drop_dir)):
        return f"Manual correction: {_NONE_STATUS}"

    data = load(drop_dir)
    cams = data.get('cameras', {})
    removed, added, relabelled, last = _totals(data)
    edited     = _edited_cameras(cams)
    total_cams = count_cameras(drop_dir, data) or len(cams)

    live = None
    if cam_id is not None and frames_total:
        stored = cams.get(str(cam_id), {}).get('frames_seen', []) or []
        opened = len(set(frames_seen or ()) | set(stored))
        live   = f"{opened}/{frames_total} frames opened on this camera"

    if edited == 0:
        head = f"Manual correction: {_NONE_STATUS}"
        return f"{head} — {live}" if live else head

    total = removed + relabelled + added
    parts = [f"{edited}/{total_cams} cameras edited"]
    if live:
        parts.append(live)
    return (f"Manual correction: {', '.join(parts)} — "
            f"{total} correction{'s' if total != 1 else ''} "
            f"(last edit {last})")
