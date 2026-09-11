import os
import sys
import argparse
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correction_state

HDR_BG    = "1A365D"
HDR_FG    = "FFFFFF"
ROW_EVEN  = "EBF8FF"
ROW_ODD   = "FFFFFF"
SECTION   = "2B6CB0"
SECTION_FG = "FFFFFF"
TOTAL_BG  = "F0FFF4"

THIN = Side(style='thin', color="D9E2EC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

F_HDR      = Font(name="Segoe UI", size=10, bold=True, color=HDR_FG)
F_SEC      = Font(name="Segoe UI", size=10, bold=True, color=SECTION_FG)
F_BODY     = Font(name="Segoe UI", size=9)
F_BOLD     = Font(name="Segoe UI", size=9, bold=True)
F_TITLE    = Font(name="Segoe UI", size=13, bold=True, color=HDR_BG)
F_STAT_LBL = Font(name="Segoe UI", size=9, color="52606D")
F_STAT_VAL = Font(name="Segoe UI", size=11, bold=True, color=HDR_BG)

FILL_HDR      = PatternFill("solid", fgColor=HDR_BG)
FILL_EVEN     = PatternFill("solid", fgColor=ROW_EVEN)
FILL_ODD      = PatternFill("solid", fgColor=ROW_ODD)
FILL_SEC      = PatternFill("solid", fgColor=SECTION)
FILL_TOTAL    = PatternFill("solid", fgColor=TOTAL_BG)
FILL_PRESENCE = PatternFill("solid", fgColor="C6EFCE")
FILL_ABSENT   = PatternFill("solid", fgColor="F4F4F4")
FILL_SUMMARY  = PatternFill("solid", fgColor="EBF8FF")
FILL_WARN     = PatternFill("solid", fgColor="FEF3C7")
WARN_FG       = "92400E"

ALL_FAMILIES = [
    'acanthuridae', 'carangidae', 'chaetodontidae', 'haemulidae', 'holocentridae',
    'labridae', 'lutjanidae', 'pomacentridae', 'scaridae', 'scombridae',
    'serranidae', 'sphyraenidae', 'unknown',
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
    'latitude': 'Latitude', 'longitude': 'Longitude', 'drop_id': 'Drop ID', 'date': 'Date',
    'camera': 'Camera', 'n_frames': 'N frames', 'frame': 'Frame', 'time_s': 'Time (s)',
    'time_after_t0': 'Time after T0 (s)',
    'family': 'Family', 'genus': 'Genus', 'species': 'Species (scientific)',
    'count': 'Count', 'confidence': 'Confidence',
    'habitat': 'Habitat', 'visibility': 'Visibility', 'depth': 'Depth',
}


def _normalise_unknown(df):
    """Accepte l'ancien libellé français d'une détection non identifiée.

    Le label était 'inconnu' jusqu'à la 1.3.0 — un mot français au milieu de
    sorties entièrement anglaises. Renommé 'unknown', mais des fichiers corrigés
    avec une version antérieure peuvent encore porter l'ancien ; sans cette
    conversion ils apparaîtraient comme une famille de plus, hors du tableau.
    """
    for col in ('family', 'genus', 'species'):
        if col in df.columns:
            df[col] = df[col].replace('inconnu', 'unknown')
    return df


def _set_border(cell):
    cell.border = BORDER


def _write_section_header(ws, row, col, text, n_cols):
    cell = ws.cell(row=row, column=col, value=text)
    cell.fill = FILL_SEC
    cell.font = F_SEC
    cell.alignment = Alignment(horizontal='center', vertical='center')
    if n_cols > 1:
        ws.merge_cells(
            start_row=row, start_column=col,
            end_row=row, end_column=col + n_cols - 1
        )
    return row + 1


def _write_table(ws, start_row, start_col, headers, rows, totals=None):
    for c, h in enumerate(headers, start_col):
        cell = ws.cell(row=start_row, column=c, value=h)
        cell.fill = FILL_HDR
        cell.font = F_HDR
        cell.alignment = Alignment(horizontal='center', vertical='center')
        _set_border(cell)

    for r_idx, row in enumerate(rows, start_row + 1):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        for c_idx, val in enumerate(row, start_col):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.fill = fill
            cell.font = F_BODY
            cell.alignment = Alignment(
                horizontal='right' if isinstance(val, (int, float)) else 'left',
                vertical='center',
            )
            _set_border(cell)

    end_row = start_row + len(rows)

    if totals:
        for c_idx, val in enumerate(totals, start_col):
            cell = ws.cell(row=end_row + 1, column=c_idx, value=val)
            cell.fill = FILL_TOTAL
            cell.font = F_BOLD
            cell.alignment = Alignment(
                horizontal='right' if isinstance(val, (int, float)) else 'left',
                vertical='center',
            )
            _set_border(cell)
        end_row += 1

    return end_row + 2


def _build_detections_sheet(wb, df):
    ws = wb.active
    ws.title = "Detections"
    ws.sheet_view.zoomScale = 100

    cols = list(df.columns)

    for c_idx, col in enumerate(cols, 1):
        label = COL_LABELS.get(col, col)
        cell = ws.cell(row=1, column=c_idx, value=label)
        cell.fill = FILL_HDR
        cell.font = F_HDR
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=False)
        ws.column_dimensions[get_column_letter(c_idx)].width = COL_WIDTHS.get(col, 12)

    ws.row_dimensions[1].height = 22

    for r_idx, row_data in enumerate(df.itertuples(index=False), 2):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        for c_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.fill = fill
            cell.font = F_BODY
            col_name = cols[c_idx - 1]
            cell.alignment = Alignment(
                horizontal='right' if col_name in ('frame', 'time_s', 'time_after_t0',
                                                    'count', 'confidence') else 'left',
                vertical='center',
            )

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _build_summary_sheet(wb, df):
    ws = wb.create_sheet("Summary")
    ws.sheet_view.zoomScale = 100
    ws.column_dimensions['A'].width = 22
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 16
    ws.column_dimensions['E'].width = 16

    row = 1

    cell = ws.cell(row=row, column=1, value="RENAI — Detection summary")
    cell.font = F_TITLE
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 2

    row = _write_section_header(ws, row, 1, "GENERAL STATISTICS", 2)

    stats = [
        ("Total detections",    len(df)),
        ("Distinct families",   df['family'].nunique()),
        ("Cameras",             df['camera'].nunique()),
    ]
    if 'site' in df.columns and df['site'].nunique() > 0:
        stats.append(("Sites", df['site'].nunique()))
    if 'time_after_t0' in df.columns:
        dur = df['time_after_t0'].max() - df['time_after_t0'].min()
        stats.append(("Duration covered (s)", round(dur, 1)))

    for label, val in stats:
        lbl_cell = ws.cell(row=row, column=1, value=label)
        lbl_cell.font = F_STAT_LBL
        val_cell = ws.cell(row=row, column=2, value=val)
        val_cell.font = F_STAT_VAL
        val_cell.alignment = Alignment(horizontal='left')
        row += 1
    row += 1

    row = _write_section_header(ws, row, 1, "BY FAMILY", 5)

    by_fam = (
        df.groupby('family', as_index=False)
        .agg(detections=('family', 'count'),
             count_total=('count', 'sum'),
             confidence_avg=('confidence', 'mean'))
        .sort_values('count_total', ascending=False)
    )
    by_fam['confidence_avg'] = by_fam['confidence_avg'].round(3)
    by_fam['pct'] = (by_fam['count_total'] / by_fam['count_total'].sum() * 100).round(1)

    headers = ['Family', 'Detections', 'Total count', 'Avg. confidence', '% of total']
    fam_rows = [
        (r['family'], r['detections'], r['count_total'],
         r['confidence_avg'], f"{r['pct']} %")
        for _, r in by_fam.iterrows()
    ]
    totals = ['TOTAL', len(df), int(by_fam['count_total'].sum()), '', '100 %']
    row = _write_table(ws, row, 1, headers, fam_rows, totals=totals)

    row = _write_section_header(ws, row, 1, "BY CAMERA", 4)

    by_cam = (
        df.groupby('camera', as_index=False)
        .agg(detections=('family', 'count'),
             count_total=('count', 'sum'),
             families=('family', lambda x: len(x.unique())))
        .sort_values('camera')
    )
    headers_cam = ['Camera', 'Detections', 'Total count', 'Distinct families']
    cam_rows = [
        (r['camera'], r['detections'], r['count_total'], r['families'])
        for _, r in by_cam.iterrows()
    ]
    totals_cam = ['TOTAL', len(df), int(by_cam['count_total'].sum()),
                  df['family'].nunique()]
    _write_table(ws, row, 1, headers_cam, cam_rows, totals=totals_cam)


def _count_real_observations(df, drop_dir):
    """Frames the drop was scored on — the MeanCount denominator.

    Counted per camera, not as one global total: falling back only when the
    grand total reached zero meant that deleting the frames of one camera out of
    four shrank the denominator silently and pushed MeanCount *up*. Each camera
    now falls back on its own to the n_frames recorded in the CSV, so a partial
    deletion changes nothing.
    """
    per_cam = {}
    if not df.empty and 'n_frames' in df.columns and 'camera' in df.columns:
        for cam, n in df.groupby('camera')['n_frames'].first().items():
            try:
                per_cam[str(cam)] = int(n)
            except (TypeError, ValueError):
                continue

    if drop_dir and os.path.isdir(str(drop_dir)):
        for entry in sorted(os.listdir(str(drop_dir))):
            if not entry.endswith('_frames'):
                continue
            frames_path = os.path.join(str(drop_dir), entry)
            if not os.path.isdir(frames_path):
                continue
            cam_id = entry[:-len('_frames')]
            on_disk = len([f for f in os.listdir(frames_path)
                           if f.lower().endswith('.jpg')])
            # The CSV value is what the drop was actually scored on; trust the
            # disk only when it is not obviously truncated.
            per_cam[cam_id] = max(on_disk, per_cam.get(cam_id, 0))

    return sum(per_cam.values())


def _build_indicators_sheet(wb, df, drop_dir=None):
    ws = wb.create_sheet("Indicators")
    ws.sheet_view.zoomScale = 100

    N_FAM     = len(ALL_FAMILIES)
    COL_FAM_0 = 4
    COL_TOTAL = COL_FAM_0 + N_FAM   # = 16

    ws.column_dimensions['A'].width = 24
    ws.column_dimensions['B'].width = 8
    ws.column_dimensions['C'].width = 10
    for i in range(N_FAM):
        ws.column_dimensions[get_column_letter(COL_FAM_0 + i)].width = 13
    ws.column_dimensions[get_column_letter(COL_TOTAL)].width = 9

    # ── Pre-compute indicators ────────────────────────────────────────────────
    families_detected = set(df['family'].unique()) if not df.empty else set()
    total_obs = _count_real_observations(df, drop_dir)
    corr_status, corr_warning = correction_state.drop_summary(drop_dir)
    time_col  = 'time_after_t0' if 'time_after_t0' in df.columns else 'time_s'

    total_by_fam = {fam: int((df['family'] == fam).sum()) for fam in ALL_FAMILIES}

    tofs_by_fam = {}
    for fam in ALL_FAMILIES:
        sub = df[df['family'] == fam]
        tofs_by_fam[fam] = round(float(sub[time_col].min()), 1) if not sub.empty else None

    mc_by_fam = {}
    for fam in ALL_FAMILIES:
        mc_by_fam[fam] = (round(total_by_fam[fam] / total_obs, 4)
                          if total_obs > 0 else None)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _merged_label(row, text, fill=FILL_SUMMARY, color=SECTION):
        c = ws.cell(row=row, column=1, value=text)
        c.fill = fill
        c.font = Font(name="Segoe UI", size=9, bold=True, color=color)
        c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        for col in (2, 3):
            ws.cell(row=row, column=col).fill = fill

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

    def _write_fam_row(row, vals, bold_nz=False, fill=FILL_SUMMARY):
        running = 0
        for i, fam in enumerate(ALL_FAMILIES):
            col = COL_FAM_0 + i
            val = vals.get(fam)
            if val is None:
                display, color = "—", "A0A0A0"
            else:
                display = val
                color = ("C0C0C0" if val == 0
                         else ("1F2933" if not bold_nz else HDR_BG))
                running += val
            c = ws.cell(row=row, column=col, value=display)
            c.fill = fill
            c.font = Font(name="Segoe UI", size=9,
                          bold=(bold_nz and isinstance(val, (int, float)) and val > 0),
                          color=color)
            c.alignment = Alignment(
                horizontal='right' if isinstance(display, (int, float)) else 'center',
                vertical='center')
            _set_border(c)
        return running

    # ── Row 1 : reliability banner ────────────────────────────────────────────
    # Deliberately above everything else: whoever opens this sheet sees what the
    # two indicators further down are worth before reading a single number.
    c = ws.cell(row=1, column=1, value=correction_state.banner())
    c.fill = FILL_WARN
    c.font = Font(name="Segoe UI", size=9, bold=True, color=WARN_FG)
    c.alignment = Alignment(horizontal='left', vertical='center',
                            indent=1, wrap_text=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=COL_TOTAL)
    for col in range(2, COL_TOTAL + 1):
        ws.cell(row=1, column=col).fill = FILL_WARN
    ws.row_dimensions[1].height = 30

    # ── Row 3 : family column headers ─────────────────────────────────────────
    row = 3
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        c = ws.cell(row=row, column=col, value=fam.capitalize())
        c.fill = FILL_HDR
        c.font = Font(name="Segoe UI", size=8, bold=True, color=HDR_FG)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _set_border(c)
    c = ws.cell(row=row, column=COL_TOTAL, value="TOTAL")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _set_border(c)
    ws.row_dimensions[row].height = 36
    row += 1

    # ── Row 2 : Détectée ──────────────────────────────────────────────────────
    _merged_label(row, "Detected")
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        det = fam in families_detected
        c = ws.cell(row=row, column=col, value="●" if det else "○")
        c.fill = FILL_PRESENCE if det else FILL_ABSENT
        c.font = Font(name="Segoe UI", size=12, bold=True,
                      color="2F855A" if det else "A0A0A0")
        c.alignment = Alignment(horizontal='center', vertical='center')
        _set_border(c)
    n_det = len(families_detected)
    c = ws.cell(row=row, column=COL_TOTAL, value=f"{n_det}/{N_FAM}")
    c.fill = FILL_SUMMARY
    c.font = Font(name="Segoe UI", size=10, bold=True, color=HDR_BG)
    c.alignment = Alignment(horizontal='center', vertical='center')
    _set_border(c)
    row += 2   # + blank row

    # ── Row 4 : Total détections ──────────────────────────────────────────────
    _merged_label(row, "Total detections")
    grand_total = _write_fam_row(row, total_by_fam, bold_nz=True)
    c = ws.cell(row=row, column=COL_TOTAL, value=int(grand_total))
    c.fill = FILL_SUMMARY
    c.font = Font(name="Segoe UI", size=9, bold=True, color=HDR_BG)
    c.alignment = Alignment(horizontal='right', vertical='center')
    _set_border(c)
    row += 1

    # ── Row 5 : N observations réelles ───────────────────────────────────────
    _merged_label(row, "Actual observations")
    n_cams = df['camera'].nunique() if not df.empty else 0
    approx_fpc = (total_obs // n_cams) if n_cams > 0 else "?"
    obs_desc = (f"{total_obs} obs.  ({n_cams} cam x ~{approx_fpc} frames)"
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

    # ── Manual correction — what the two indicators below actually rest on ────
    if corr_status:
        _merged_label(row, "Manual correction")
        _write_note(row, corr_status)
        row += 1
    if corr_warning:
        _merged_label(row, "⚠ Mixed basis", fill=FILL_WARN, color=WARN_FG)
        _write_note(row, corr_warning, fill=FILL_WARN, color=WARN_FG)
        row += 1

    # ── MeanCount ─────────────────────────────────────────────────────────────
    _merged_label(row, "MeanCount")
    _write_fam_row(row, mc_by_fam)
    row += 1

    # ── Row 7 : TOFS (s) ──────────────────────────────────────────────────────
    _merged_label(row, "TOFS (s)")
    _write_fam_row(row, tofs_by_fam)
    row += 2   # + blank row

    # ── Separator ─────────────────────────────────────────────────────────────
    c = ws.cell(row=row, column=1, value="— DETAIL — counts per frame per camera")
    c.fill = FILL_SEC; c.font = F_SEC
    c.alignment = Alignment(horizontal='left', vertical='center', indent=1)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=COL_TOTAL)
    for col in range(2, COL_TOTAL + 1):
        ws.cell(row=row, column=col).fill = FILL_SEC
    row += 1

    # ── Detail header ─────────────────────────────────────────────────────────
    for col_idx, hdr in enumerate(['Camera', 'Frame', 't (s)'], start=1):
        c = ws.cell(row=row, column=col_idx, value=hdr)
        c.fill = FILL_HDR; c.font = F_HDR
        c.alignment = Alignment(horizontal='center', vertical='center')
        _set_border(c)
    for i, fam in enumerate(ALL_FAMILIES):
        col = COL_FAM_0 + i
        c = ws.cell(row=row, column=col, value=fam.capitalize())
        c.fill = FILL_HDR
        c.font = Font(name="Segoe UI", size=8, bold=True, color=HDR_FG)
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        _set_border(c)
    c = ws.cell(row=row, column=COL_TOTAL, value="TOTAL")
    c.fill = FILL_HDR; c.font = F_HDR
    c.alignment = Alignment(horizontal='center', vertical='center')
    _set_border(c)
    ws.row_dimensions[row].height = 36
    row += 1

    ws.freeze_panes = f"A{row}"

    # ── Detail data ───────────────────────────────────────────────────────────
    if df.empty:
        return

    frame_counts = (
        df.groupby(['camera', 'frame', time_col, 'family'])
        .size().reset_index(name='n')
    )
    pivot = (
        frame_counts
        .pivot_table(index=['camera', 'frame', time_col],
                     columns='family', values='n', fill_value=0)
        .reset_index()
    )
    pivot.columns.name = None
    for fam in ALL_FAMILIES:
        if fam not in pivot.columns:
            pivot[fam] = 0
    pivot = pivot.sort_values(['camera', 'frame']).reset_index(drop=True)

    F_ZERO = Font(name="Segoe UI", size=9, color="C0C0C0")
    F_VAL  = Font(name="Segoe UI", size=9)
    F_TOT  = Font(name="Segoe UI", size=9, bold=True)
    F_TOT0 = Font(name="Segoe UI", size=9, color="C0C0C0")

    for r_idx, rec in enumerate(pivot.to_dict('records'), start=row):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        for col_idx, val in enumerate(
                [rec['camera'], int(rec['frame']), rec[time_col]], start=1):
            c = ws.cell(row=r_idx, column=col_idx, value=val)
            c.fill = fill; c.font = F_BODY
            c.alignment = Alignment(
                horizontal='left' if col_idx == 1 else 'right',
                vertical='center')
            _set_border(c)
        row_sum = 0
        for i, fam in enumerate(ALL_FAMILIES):
            col = COL_FAM_0 + i
            val = int(rec.get(fam, 0))
            row_sum += val
            c = ws.cell(row=r_idx, column=col, value=val)
            c.fill = fill
            c.font = F_ZERO if val == 0 else F_VAL
            c.alignment = Alignment(horizontal='right', vertical='center')
            _set_border(c)
        c = ws.cell(row=r_idx, column=COL_TOTAL, value=row_sum)
        c.fill = fill
        c.font = F_TOT0 if row_sum == 0 else F_TOT
        c.alignment = Alignment(horizontal='right', vertical='center')
        _set_border(c)


def _build_species_sheet(wb, df):
    ws = wb.create_sheet("Species")
    ws.sheet_view.zoomScale = 100

    if 'species' not in df.columns:
        ws.cell(row=1, column=1, value="No species data in this drop.")
        return

    sp_df = df[df['species'].notna() & (df['species'].astype(str) != '')].copy()
    if sp_df.empty:
        ws.cell(row=1, column=1, value="No species identified in this drop.")
        return

    by_sp = (
        sp_df.groupby(['family', 'genus', 'species'], as_index=False)
        .agg(detections=('species', 'count'),
             n_frames=('frame', 'nunique'),
             n_cameras=('camera', 'nunique'))
        .sort_values(['family', 'detections'], ascending=[True, False])
        .reset_index(drop=True)
    )

    headers = ['Family', 'Genus', 'Species (scientific)', 'Detections', 'N frames', 'N cameras']
    widths  = [16, 14, 26, 13, 11, 13]

    for c_idx, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=c_idx, value=h)
        cell.fill = FILL_HDR
        cell.font = F_HDR
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(c_idx)].width = w

    for r_idx, row in enumerate(by_sp.itertuples(index=False), 2):
        fill = FILL_EVEN if r_idx % 2 == 0 else FILL_ODD
        vals = [row.family, row.genus, row.species,
                row.detections, row.n_frames, row.n_cameras]
        for c_idx, val in enumerate(vals, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.fill = fill
            cell.font = F_BODY
            cell.alignment = Alignment(
                horizontal='right' if isinstance(val, (int, float)) else 'left',
                vertical='center',
            )
            _set_border(cell)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',    required=True)
    parser.add_argument('--output',   required=True)
    parser.add_argument('--drop_dir', default=None,
                        help='Drop results folder — used to count real observations')
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[WARN] CSV not found: {args.input}")
        return

    df = pd.read_csv(args.input)
    if df.empty:
        print("[WARN] Empty CSV, Excel not generated.")
        return
    df = _normalise_unknown(df)

    wb = Workbook()
    _build_detections_sheet(wb, df)
    _build_summary_sheet(wb, df)
    _build_indicators_sheet(wb, df, drop_dir=args.drop_dir)
    _build_species_sheet(wb, df)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    wb.save(args.output)
    print(f"Excel saved to {args.output} — {len(df)} detections, "
          f"{df['family'].nunique()} families")


if __name__ == '__main__':
    main()
