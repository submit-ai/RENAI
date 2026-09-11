import os
import sys
import json
import argparse
import glob
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correction_state

HDR_BG     = "1A365D"
HDR_FG     = "FFFFFF"
ROW_EVEN   = "EBF8FF"
ROW_ODD    = "FFFFFF"
SECTION    = "2B6CB0"
SECTION_FG = "FFFFFF"
TOTAL_BG   = "F0FFF4"
WARN_BG    = "FFF5F5"
OK_BG      = "F0FFF4"

THIN   = Side(style='thin', color="D9E2EC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

F_HDR      = Font(name="Segoe UI", size=10, bold=True,  color=HDR_FG)
F_BODY     = Font(name="Segoe UI", size=9)
F_BOLD     = Font(name="Segoe UI", size=9,  bold=True)
F_TITLE    = Font(name="Segoe UI", size=13, bold=True,  color=HDR_BG)
F_SMALL    = Font(name="Segoe UI", size=8,  color="52606D")

FILL_HDR      = PatternFill("solid", fgColor=HDR_BG)
FILL_EVEN     = PatternFill("solid", fgColor=ROW_EVEN)
FILL_ODD      = PatternFill("solid", fgColor=ROW_ODD)
FILL_TOTAL    = PatternFill("solid", fgColor=TOTAL_BG)
FILL_WARN     = PatternFill("solid", fgColor=WARN_BG)
FILL_OK       = PatternFill("solid", fgColor=OK_BG)
FILL_SUMMARY  = PatternFill("solid", fgColor="EBF8FF")
FILL_BANNER   = PatternFill("solid", fgColor="FEF3C7")
BANNER_FG     = "92400E"

ALL_FAMILIES = [
    'acanthuridae', 'carangidae', 'chaetodontidae', 'haemulidae', 'holocentridae',
    'labridae', 'lutjanidae', 'pomacentridae', 'scaridae', 'scombridae',
    'serranidae', 'sphyraenidae', 'inconnu',
]

COL_WIDTHS = {
    'campaign': 16, 'location': 16, 'site': 14,
    'latitude': 12, 'longitude': 12, 'drop_id': 14, 'date': 13,
    'camera': 10, 'n_frames': 10, 'frame': 8, 'time_s': 11, 'time_after_t0': 15,
    'family': 16, 'genus': 14, 'species': 24, 'count': 9, 'confidence': 12,
    'habitat': 14, 'visibility': 13, 'depth': 13,
}

COL_LABELS = {
    'campaign': 'Campaign', 'location': 'Location', 'site': 'Site',
    'latitude': 'Latitude', 'longitude': 'Longitude',
    'drop_id': 'Drop ID', 'date': 'Date',
    'camera': 'Camera', 'n_frames': 'N frames', 'frame': 'Frame',
    'time_s': 'Time (s)', 'time_after_t0': 'Time after T0 (s)',
    'family': 'Family', 'genus': 'Genus', 'species': 'Species (scientific)',
    'count': 'Count', 'confidence': 'Confidence',
    'habitat': 'Habitat', 'visibility': 'Visibility', 'depth': 'Depth',
}

META_FIELDS = ['date', 'site', 'latitude', 'longitude', 'habitat', 'visibility', 'depth']


def _border(cell):
    cell.border = BORDER


def _build_detections_sheet(wb, df):
    ws = wb.active
    ws.title = "Detections"
    ws.sheet_view.zoomScale = 100

    cols = list(df.columns)
    for c_idx, col in enumerate(cols, 1):
        cell = ws.cell(row=1, column=c_idx, value=COL_LABELS.get(col, col))
        cell.fill = FILL_HDR
        cell.font = F_HDR
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(c_idx)].width = COL_WIDTHS.get(col, 12)
        _border(cell)

    ws.row_dimensions[1].height = 22

    for r_idx, row_data in enumerate(df.itertuples(index=False), 2):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        for c_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.fill = fill
            cell.font = F_BODY
            col_name = cols[c_idx - 1]
            cell.alignment = Alignment(
                horizontal='right' if col_name in (
                    'frame', 'n_frames', 'time_s', 'time_after_t0',
                    'count', 'confidence', 'latitude', 'longitude') else 'left',
                vertical='center',
            )
            _border(cell)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _build_qc_sheet(wb, df, results_dir):
    ws = wb.create_sheet("QC per drop")
    ws.sheet_view.zoomScale = 100

    cell = ws.cell(row=1, column=1, value="RENAI — Quality control per drop")
    cell.font = F_TITLE
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=10)

    frames_per_cam = (
        df.groupby(['drop_id', 'camera'])['n_frames'].first()
        .reset_index()
    )
    frames_total = (
        frames_per_cam.groupby('drop_id')['n_frames'].sum()
        .reset_index().rename(columns={'n_frames': 'n_frames_total'})
    )

    qc = df.groupby('drop_id').agg(
        n_cameras   =('camera',  'nunique'),
        n_detections=('family',  'count'),
        n_families  =('family',  'nunique'),
    ).reset_index()
    qc = qc.merge(frames_total, on='drop_id', how='left')

    avail_meta = [c for c in META_FIELDS if c in df.columns]
    if avail_meta:
        meta_df = df.groupby('drop_id')[avail_meta].first().reset_index()
        qc = qc.merge(meta_df, on='drop_id', how='left')

    all_drop_dirs = [
        d for d in glob.glob(os.path.join(results_dir, '*'))
        if os.path.isdir(d) and
        os.path.isfile(os.path.join(d, 'drop_metadata.json'))
    ]
    csv_drops = set(qc['drop_id'].tolist())
    for drop_dir in all_drop_dirs:
        dn = os.path.basename(drop_dir)
        if dn in csv_drops:
            continue
        meta_path = os.path.join(drop_dir, 'drop_metadata.json')
        try:
            with open(meta_path, encoding='utf-8') as f:
                m = json.load(f)
        except Exception:
            m = {}
        row = {'drop_id': dn, 'n_cameras': 0, 'n_detections': 0,
               'n_families': 0, 'n_frames_total': 0}
        for field in avail_meta:
            row[field] = m.get(field, '')
        qc = pd.concat([qc, pd.DataFrame([row])], ignore_index=True)

    qc = qc.sort_values('drop_id').reset_index(drop=True)

    def _flag(row):
        for field in META_FIELDS:
            val = row.get(field, '')
            if pd.isna(val) or str(val).strip() == '':
                return '⚠️ Missing data'
        return '✅ OK'
    qc['qc'] = qc.apply(_flag, axis=1)

    col_order = (['drop_id', 'n_cameras', 'n_frames_total', 'n_detections', 'n_families']
                 + [c for c in avail_meta] + ['qc'])
    col_order = [c for c in col_order if c in qc.columns]
    qc = qc[col_order]

    headers = {
        'drop_id':        'Drop ID',
        'n_cameras':      'N cameras',
        'n_frames_total': 'N frames total',
        'n_detections':   'N detections',
        'n_families':     'N families',
        'date':           'Date',
        'site':           'Site',
        'latitude':       'Latitude',
        'longitude':      'Longitude',
        'habitat':        'Habitat',
        'visibility':     'Visibility',
        'depth':          'Depth',
        'qc':             'QC',
    }
    col_w = {
        'drop_id': 16, 'n_cameras': 11, 'n_frames_total': 15,
        'n_detections': 14, 'n_families': 14,
        'date': 13, 'site': 14, 'latitude': 12, 'longitude': 12,
        'habitat': 14, 'visibility': 13, 'depth': 13, 'qc': 22,
    }

    hdr_row = 3
    for c_idx, col in enumerate(col_order, 1):
        cell = ws.cell(row=hdr_row, column=c_idx, value=headers.get(col, col))
        cell.fill = FILL_HDR
        cell.font = F_HDR
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(c_idx)].width = col_w.get(col, 12)
        _border(cell)
    ws.row_dimensions[hdr_row].height = 22

    num_cols = {'n_cameras', 'n_frames_total', 'n_detections', 'n_families',
                'latitude', 'longitude'}

    for r_idx, (_, row) in enumerate(qc.iterrows(), hdr_row + 1):
        is_warn = str(row.get('qc', '')).startswith('⚠️')
        fill = FILL_WARN if is_warn else (FILL_EVEN if r_idx % 2 == 0 else FILL_ODD)
        for c_idx, col in enumerate(col_order, 1):
            val = row.get(col, '')
            if pd.isna(val):
                val = ''
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.fill = fill
            cell.font = F_BOLD if col == 'qc' else F_BODY
            cell.alignment = Alignment(
                horizontal='right' if col in num_cols else 'left',
                vertical='center',
            )
            _border(cell)

    total_row = hdr_row + len(qc) + 1
    totals = {
        'drop_id':        'TOTAL',
        'n_cameras':      '',
        'n_frames_total': int(qc['n_frames_total'].sum()),
        'n_detections':   int(qc['n_detections'].sum()),
        'n_families':     df['family'].nunique() if not df.empty else 0,
    }
    for c_idx, col in enumerate(col_order, 1):
        val = totals.get(col, '')
        cell = ws.cell(row=total_row, column=c_idx, value=val)
        cell.fill = FILL_TOTAL
        cell.font = F_BOLD
        cell.alignment = Alignment(
            horizontal='right' if col in num_cols else 'left',
            vertical='center',
        )
        _border(cell)

    ws.freeze_panes = f"A{hdr_row + 1}"


def _all_processed_drops(results_dir, df):
    """Return sorted list of all processed drop_ids (including drops with 0 detections)."""
    drops = set()
    if results_dir and os.path.isdir(str(results_dir)):
        for entry in os.listdir(str(results_dir)):
            if os.path.isfile(os.path.join(str(results_dir), entry, 'drop_metadata.json')):
                drops.add(entry)
    if not drops and 'drop_id' in df.columns:
        drops = {x for x in df['drop_id'].unique() if pd.notna(x)}
    return sorted(drops)


def _count_campaign_observations(df, results_dir):
    """Frames the campaign was scored on — the pooled MeanCount denominator.

    Counted per (drop, camera) for the same reason as in generate_excel.py:
    a global zero-fallback let a partial deletion of {cam}_frames/ shrink the
    denominator without a word, which inflates MeanCount.
    """
    per_cam = {}
    if not df.empty and 'n_frames' in df.columns \
            and {'drop_id', 'camera'} <= set(df.columns):
        for (drop_id, cam), n in df.groupby(['drop_id', 'camera'])['n_frames'].first().items():
            try:
                per_cam[(str(drop_id), str(cam))] = int(n)
            except (TypeError, ValueError):
                continue

    if results_dir and os.path.isdir(str(results_dir)):
        for drop_entry in sorted(os.listdir(str(results_dir))):
            drop_path = os.path.join(str(results_dir), drop_entry)
            if not os.path.isdir(drop_path):
                continue
            for entry in os.listdir(drop_path):
                if not entry.endswith('_frames'):
                    continue
                frames_path = os.path.join(drop_path, entry)
                if not os.path.isdir(frames_path):
                    continue
                key = (drop_entry, entry[:-len('_frames')])
                on_disk = len([f for f in os.listdir(frames_path)
                               if f.lower().endswith('.jpg')])
                per_cam[key] = max(on_disk, per_cam.get(key, 0))

    return sum(per_cam.values())


def _build_campaign_indicators_sheet(wb, df, results_dir=None):
    ws = wb.create_sheet("Indicators")
    ws.sheet_view.zoomScale = 100

    N_FAM     = len(ALL_FAMILIES)
    COL_FAM_0 = 2
    COL_TOTAL = COL_FAM_0 + N_FAM   # = 14

    ws.column_dimensions['A'].width = 28
    for i in range(N_FAM):
        ws.column_dimensions[get_column_letter(COL_FAM_0 + i)].width = 13
    ws.column_dimensions[get_column_letter(COL_TOTAL)].width = 9

    # ── Pre-compute ───────────────────────────────────────────────────────────
    all_drops = _all_processed_drops(results_dir, df)
    n_drops   = len(all_drops)
    time_col  = 'time_after_t0' if 'time_after_t0' in df.columns else 'time_s'
    total_obs = _count_campaign_observations(df, results_dir)
    corr_status, corr_warning = correction_state.campaign_summary(results_dir)

    stats = {}
    for fam in ALL_FAMILIES:
        fam_df = df[df['family'] == fam] if not df.empty else pd.DataFrame()
        if not fam_df.empty and 'drop_id' in fam_df.columns:
            n_drops_fam   = int(fam_df['drop_id'].nunique())
            tofs_per_drop = fam_df.groupby('drop_id')[time_col].min()
            tofs_min      = round(float(tofs_per_drop.min()),  1)
            tofs_mean     = round(float(tofs_per_drop.mean()), 1)
        else:
            n_drops_fam = 0
            tofs_min    = None
            tofs_mean   = None
        total_det = int((df['family'] == fam).sum()) if not df.empty else 0
        occ_freq  = round(n_drops_fam / n_drops * 100, 1) if n_drops > 0 else 0.0
        mc        = round(total_det / total_obs, 4) if total_obs > 0 else None
        stats[fam] = dict(drops=n_drops_fam, occ=occ_freq,
                          tofs_min=tofs_min, tofs_mean=tofs_mean,
                          total_det=total_det, mc=mc)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _lbl(row, text, fill=FILL_SUMMARY, color=SECTION):
        c = ws.cell(row=row, column=1, value=text)
        c.fill = fill
        c.font = Font(name="Segoe UI", size=9, bold=True, color=color)
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        _border(c)

    def _write_note(row, text, fill=FILL_SUMMARY, color="52606D"):
        """Free-text value spanning the family columns — same look as the
        'Actual observations' line."""
        c = ws.cell(row=row, column=COL_FAM_0, value=text)
        c.fill = fill
        c.font = Font(name="Segoe UI", size=9, color=color)
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.merge_cells(start_row=row, start_column=COL_FAM_0,
                       end_row=row, end_column=COL_TOTAL)
        for col in range(COL_FAM_0 + 1, COL_TOTAL + 1):
            ws.cell(row=row, column=col).fill = fill

    def _fam_row(row, key, grand_total_val=None):
        for i, fam in enumerate(ALL_FAMILIES):
            col = COL_FAM_0 + i
            val = stats[fam][key]
            display = "—" if val is None else val
            color   = ("A0A0A0" if val is None
                       else "C0C0C0" if val == 0
                       else "1F2933")
            c = ws.cell(row=row, column=col, value=display)
            c.fill = FILL_SUMMARY
            c.font = Font(name="Segoe UI", size=9,
                          bold=(key == 'total_det' and val not in (None, 0)),
                          color=color)
            c.alignment = Alignment(
                horizontal='right' if isinstance(display, (int, float)) else 'center',
                vertical='center')
            _border(c)
        if grand_total_val is not None:
            c = ws.cell(row=row, column=COL_TOTAL, value=grand_total_val)
            c.fill = FILL_SUMMARY
            c.font = Font(name="Segoe UI", size=9, bold=True, color=HDR_BG)
            c.alignment = Alignment(horizontal='right', vertical='center')
            _border(c)

    # ── Row 1: reliability banner ─────────────────────────────────────────────
    # Deliberately above everything else: whoever opens this sheet sees what the
    # indicators further down are worth before reading a single number.
    c = ws.cell(row=1, column=1, value=correction_state.banner())
    c.fill = FILL_BANNER
    c.font = Font(name="Segoe UI", size=9, bold=True, color=BANNER_FG)
    c.alignment = Alignment(horizontal='left', vertical='center',
                            indent=1, wrap_text=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=COL_TOTAL)
    for col in range(2, COL_TOTAL + 1):
        ws.cell(row=1, column=col).fill = FILL_BANNER
    ws.row_dimensions[1].height = 30

    # ── Row 3: family headers ─────────────────────────────────────────────────
    row = 3
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        c = ws.cell(row=row, column=col, value=fam.capitalize())
        c.fill = FILL_HDR
        c.font = Font(name="Segoe UI", size=8, bold=True, color=HDR_FG)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _border(c)
    c = ws.cell(row=row, column=COL_TOTAL, value="TOTAL")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _border(c)
    ws.row_dimensions[row].height = 36
    row += 1

    # ── N drops present ───────────────────────────────────────────────────────
    _lbl(row, f"N drops with detections  (/ {n_drops} drops)")
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        d = stats[fam]['drops']
        c = ws.cell(row=row, column=col, value=f"{d}/{n_drops}")
        c.fill = FILL_SUMMARY
        c.font = Font(name="Segoe UI", size=9,
                      bold=(d > 0), color="1F2933" if d > 0 else "A0A0A0")
        c.alignment = Alignment(horizontal='center', vertical='center')
        _border(c)
    row += 1

    # ── Occurrence frequency ──────────────────────────────────────────────────
    _lbl(row, "Occurrence frequency")
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        occ = stats[fam]['occ']
        c = ws.cell(row=row, column=col, value=f"{occ:.1f}%")
        c.fill = FILL_SUMMARY
        c.font = Font(name="Segoe UI", size=9,
                      color="1F2933" if occ > 0 else "C0C0C0")
        c.alignment = Alignment(horizontal='center', vertical='center')
        _border(c)
    row += 2   # + blank

    # ── TOFS min ──────────────────────────────────────────────────────────────
    _lbl(row, "TOFS min (s)")
    _fam_row(row, 'tofs_min')
    row += 1

    # ── TOFS mean ─────────────────────────────────────────────────────────────
    _lbl(row, "TOFS mean (s)")
    _fam_row(row, 'tofs_mean')
    row += 2   # + blank

    # ── Total detections ──────────────────────────────────────────────────────
    _lbl(row, "Total detections")
    grand = sum(stats[fam]['total_det'] for fam in ALL_FAMILIES)
    _fam_row(row, 'total_det', grand_total_val=int(grand))
    row += 1

    # ── Actual observations ───────────────────────────────────────────────────
    _lbl(row, "Actual observations")
    obs_desc = (f"{total_obs} obs. across {n_drops} drops"
                if total_obs > 0 else "N/A")
    c = ws.cell(row=row, column=COL_FAM_0, value=obs_desc)
    c.fill = FILL_SUMMARY
    c.font = Font(name="Segoe UI", size=9, color="52606D")
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.merge_cells(start_row=row, start_column=COL_FAM_0,
                   end_row=row, end_column=COL_TOTAL)
    for col in range(COL_FAM_0 + 1, COL_TOTAL + 1):
        ws.cell(row=row, column=col).fill = FILL_SUMMARY
    row += 1

    # ── Manual correction — what the indicators below actually rest on ────────
    if corr_status:
        _lbl(row, "Manual correction")
        _write_note(row, corr_status)
        row += 1
    if corr_warning:
        _lbl(row, "⚠ Mixed basis", fill=FILL_BANNER, color=BANNER_FG)
        _write_note(row, corr_warning, fill=FILL_BANNER, color=BANNER_FG)
        row += 1

    # ── MeanCount (pooled) ────────────────────────────────────────────────────
    _lbl(row, "MeanCount (pooled)")
    _fam_row(row, 'mc')


def _build_presence_matrix_sheet(wb, df, results_dir=None):
    ws = wb.create_sheet("Presence matrix")
    ws.sheet_view.zoomScale = 100

    N_FAM     = len(ALL_FAMILIES)
    COL_FAM_0 = 2
    COL_TOTAL = COL_FAM_0 + N_FAM   # = 14

    ws.column_dimensions['A'].width = 20
    for i in range(N_FAM):
        ws.column_dimensions[get_column_letter(COL_FAM_0 + i)].width = 11
    ws.column_dimensions[get_column_letter(COL_TOTAL)].width = 9

    if df.empty or 'drop_id' not in df.columns:
        ws.cell(row=1, column=1, value="No data")
        return

    # ── Header ────────────────────────────────────────────────────────────────
    row = 1
    c = ws.cell(row=row, column=1, value="Drop ID")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _border(c)
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        c = ws.cell(row=row, column=col, value=fam.capitalize())
        c.fill = FILL_HDR
        c.font = Font(name="Segoe UI", size=8, bold=True, color=HDR_FG)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _border(c)
    c = ws.cell(row=row, column=COL_TOTAL, value="TOTAL")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _border(c)
    ws.row_dimensions[row].height = 36
    row += 1

    # ── Matrix data ───────────────────────────────────────────────────────────
    matrix = (
        df.groupby(['drop_id', 'family'])
        .size().reset_index(name='n')
        .pivot_table(index='drop_id', columns='family', values='n', fill_value=0)
        .reset_index()
    )
    matrix.columns.name = None
    for fam in ALL_FAMILIES:
        if fam not in matrix.columns:
            matrix[fam] = 0
    all_drops_pm = _all_processed_drops(results_dir, df)
    if all_drops_pm:
        matrix = (
            matrix.set_index('drop_id')
            .reindex(all_drops_pm, fill_value=0)
            .reset_index()
        )
    matrix = matrix.sort_values('drop_id').reset_index(drop=True)

    F_ZERO = Font(name="Segoe UI", size=9, color="D0D0D0")
    F_VAL  = Font(name="Segoe UI", size=9)
    F_TOT  = Font(name="Segoe UI", size=9, bold=True)
    F_TOT0 = Font(name="Segoe UI", size=9, color="D0D0D0")

    col_totals = {fam: 0 for fam in ALL_FAMILIES}

    for r_idx, rec in enumerate(matrix.to_dict('records'), start=row):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        c = ws.cell(row=r_idx, column=1, value=rec['drop_id'])
        c.fill = fill; c.font = F_VAL
        c.alignment = Alignment(horizontal='left', vertical='center')
        _border(c)
        row_sum = 0
        for i, fam in enumerate(ALL_FAMILIES):
            col = COL_FAM_0 + i
            val = int(rec.get(fam, 0))
            row_sum += val
            col_totals[fam] += val
            c = ws.cell(row=r_idx, column=col, value=val)
            c.fill = fill
            c.font = F_ZERO if val == 0 else F_VAL
            c.alignment = Alignment(horizontal='right', vertical='center')
            _border(c)
        c = ws.cell(row=r_idx, column=COL_TOTAL, value=row_sum)
        c.fill = fill
        c.font = F_TOT0 if row_sum == 0 else F_TOT
        c.alignment = Alignment(horizontal='right', vertical='center')
        _border(c)

    # ── TOTAL row ─────────────────────────────────────────────────────────────
    total_row = row + len(matrix)
    c = ws.cell(row=total_row, column=1, value="TOTAL")
    c.fill = FILL_TOTAL; c.font = F_BOLD
    c.alignment = Alignment(horizontal='left', vertical='center')
    _border(c)
    grand = 0
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        val = col_totals[fam]
        grand += val
        c = ws.cell(row=total_row, column=col, value=val)
        c.fill = FILL_TOTAL
        c.font = Font(name="Segoe UI", size=9, bold=True,
                      color="1F2933" if val > 0 else "C0C0C0")
        c.alignment = Alignment(horizontal='right', vertical='center')
        _border(c)
    c = ws.cell(row=total_row, column=COL_TOTAL, value=grand)
    c.fill = FILL_TOTAL
    c.font = Font(name="Segoe UI", size=9, bold=True, color=HDR_BG)
    c.alignment = Alignment(horizontal='right', vertical='center')
    _border(c)

    ws.freeze_panes = "A2"


def _build_species_presence_sheet(wb, df):
    ws = wb.create_sheet("Species presence")
    ws.sheet_view.zoomScale = 100

    if 'species' not in df.columns or 'drop_id' not in df.columns:
        ws.cell(row=1, column=1, value="No species data.")
        return

    sp_df = df[df['species'].notna() & (df['species'].astype(str) != '') & df['drop_id'].notna()].copy()
    if sp_df.empty:
        ws.cell(row=1, column=1, value="No species identified in this campaign.")
        return

    all_species = sorted(sp_df['species'].unique())
    all_drops   = sorted(x for x in df['drop_id'].unique() if pd.notna(x))
    N_SP        = len(all_species)
    COL_SP_0    = 2
    COL_TOTAL   = COL_SP_0 + N_SP

    ws.column_dimensions['A'].width = 20
    for i in range(N_SP):
        ws.column_dimensions[get_column_letter(COL_SP_0 + i)].width = 18
    ws.column_dimensions[get_column_letter(COL_TOTAL)].width = 9

    FILL_PRES = PatternFill("solid", fgColor="C6EFCE")
    FILL_ABS  = PatternFill("solid", fgColor="F4F4F4")
    F_SP = Font(name="Segoe UI", size=8, bold=True, color=HDR_FG)
    F_V  = Font(name="Segoe UI", size=9)
    F_Z  = Font(name="Segoe UI", size=9, color="D0D0D0")
    F_T  = Font(name="Segoe UI", size=9, bold=True)

    # Header row
    row = 1
    c = ws.cell(row=row, column=1, value="Drop ID")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _border(c)
    for i, sp in enumerate(all_species):
        col = COL_SP_0 + i
        c = ws.cell(row=row, column=col, value=sp)
        c.fill = FILL_HDR; c.font = F_SP
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _border(c)
    c = ws.cell(row=row, column=COL_TOTAL, value="TOTAL sp.")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _border(c)
    ws.row_dimensions[row].height = 52
    row += 1

    matrix = (
        sp_df.groupby(['drop_id', 'species'])
        .size().reset_index(name='n')
        .pivot_table(index='drop_id', columns='species', values='n', fill_value=0)
        .reset_index()
    )
    matrix.columns.name = None
    for sp in all_species:
        if sp not in matrix.columns:
            matrix[sp] = 0
    # Inclure tous les drops, y compris ceux sans espèces identifiées
    matrix = (
        matrix.set_index('drop_id')
        .reindex(all_drops, fill_value=0)
        .reset_index()
    )
    matrix = matrix.sort_values('drop_id').reset_index(drop=True)

    col_totals = {sp: 0 for sp in all_species}
    for r_idx, rec in enumerate(matrix.to_dict('records'), start=row):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        c = ws.cell(row=r_idx, column=1, value=rec['drop_id'])
        c.fill = fill; c.font = F_V
        c.alignment = Alignment(horizontal='left', vertical='center')
        _border(c)
        row_sum = 0
        for i, sp in enumerate(all_species):
            col = COL_SP_0 + i
            val = int(rec.get(sp, 0))
            row_sum += (1 if val > 0 else 0)
            col_totals[sp] += val
            c = ws.cell(row=r_idx, column=col, value=val if val > 0 else '')
            c.fill = FILL_PRES if val > 0 else FILL_ABS
            c.font = F_V if val > 0 else F_Z
            c.alignment = Alignment(horizontal='right', vertical='center')
            _border(c)
        c = ws.cell(row=r_idx, column=COL_TOTAL, value=row_sum)
        c.fill = fill
        c.font = F_Z if row_sum == 0 else F_T
        c.alignment = Alignment(horizontal='right', vertical='center')
        _border(c)

    total_row = row + len(matrix)
    c = ws.cell(row=total_row, column=1, value="TOTAL det.")
    c.fill = FILL_TOTAL; c.font = F_T
    c.alignment = Alignment(horizontal='left', vertical='center')
    _border(c)
    grand = 0
    for i, sp in enumerate(all_species):
        col = COL_SP_0 + i
        val = col_totals[sp]
        grand += val
        c = ws.cell(row=total_row, column=col, value=val)
        c.fill = FILL_TOTAL
        c.font = Font(name="Segoe UI", size=9, bold=True,
                      color="1F2933" if val > 0 else "C0C0C0")
        c.alignment = Alignment(horizontal='right', vertical='center')
        _border(c)
    c = ws.cell(row=total_row, column=COL_TOTAL, value=grand)
    c.fill = FILL_TOTAL
    c.font = Font(name="Segoe UI", size=9, bold=True, color=HDR_BG)
    c.alignment = Alignment(horizontal='right', vertical='center')
    _border(c)

    ws.freeze_panes = "A2"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign_csv', required=True)
    parser.add_argument('--results_dir',  required=True)
    parser.add_argument('--output',       required=True)
    args = parser.parse_args()

    if not os.path.isfile(args.campaign_csv):
        print(f"[WARN] Campaign CSV not found: {args.campaign_csv}")
        return

    df = pd.read_csv(args.campaign_csv)
    if df.empty:
        print("[WARN] Empty campaign CSV, Excel not generated.")
        return

    wb = Workbook()
    _build_detections_sheet(wb, df)
    _build_qc_sheet(wb, df, args.results_dir)
    _build_campaign_indicators_sheet(wb, df, results_dir=args.results_dir)
    _build_presence_matrix_sheet(wb, df, results_dir=args.results_dir)
    _build_species_presence_sheet(wb, df)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    wb.save(args.output)
    n_drops = df['drop_id'].nunique() if 'drop_id' in df.columns else '?'
    print(f"Campaign Excel saved to {args.output} — "
          f"{len(df)} detections, {n_drops} drops, "
          f"{df['family'].nunique()} families")


if __name__ == '__main__':
    main()
