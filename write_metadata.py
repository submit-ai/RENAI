"""Remplit drop_metadata.json pour tous les drops d'une campagne, à partir
d'un tableur de terrain (une ligne par site).

    python write_metadata.py --xlsx metadata_drop.xlsx \\
                             --campaign-dir <dossier des vidéos> \\
                             --results-dir  <dossier results/>

Les chemins sont des arguments : les coder en dur revenait à publier
l'arborescence d'une machine précise.
"""
import argparse
import os, json, re, openpyxl

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--xlsx',          required=True,
                    help="tableur de terrain (colonnes campagne, lieu, site, "
                         "lat, lon, habitat, visibilité, profondeur)")
parser.add_argument('--campaign-dir',  required=True,
                    help="dossier de la campagne : un sous-dossier par drop")
parser.add_argument('--results-dir',   required=True,
                    help="dossier results/ où écrire les drop_metadata.json")
args = parser.parse_args()

XLSX_PATH    = args.xlsx
CAMPAIGN_DIR = args.campaign_dir
RESULTS_DIR  = args.results_dir

wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(values_only=True))
wb.close()

def fmt(v):
    if v is None:
        return ""
    s = str(v).strip()
    if re.match(r"^\d+,\d+$", s):
        s = s.replace(",", ".")
    if re.match(r"^\d+\.0$", s):
        s = str(int(float(s)))
    return s

lookup = {}
for row in rows[1:]:
    if not any(row):
        continue
    campaign, location, site, lat, lon, habitat, visibility, depth = [fmt(c) for c in row[:8]]
    if not site:
        continue
    lookup[site] = {
        "campaign":   campaign,
        "location":   location,
        "site":       site,
        "latitude":   lat,
        "longitude":  lon,
        "habitat":    habitat,
        "visibility": visibility,
        "depth":      depth,
    }

written = []
skipped = []

for transect_dir in sorted(os.listdir(CAMPAIGN_DIR)):
    transect_path = os.path.join(CAMPAIGN_DIR, transect_dir)
    if not os.path.isdir(transect_path):
        continue
    for drop_name in sorted(os.listdir(transect_path)):
        drop_path = os.path.join(transect_path, drop_name)
        if not os.path.isdir(drop_path):
            continue

        m = re.search(r"DOP-(.+)$", drop_name, re.IGNORECASE)
        if not m:
            skipped.append(f"{drop_name}  [pas de DOP- dans le nom]")
            continue
        suffix = m.group(1)
        excel_site = suffix if suffix.startswith("D") else "D" + suffix

        meta = lookup.get(excel_site)
        if not meta:
            skipped.append(f"{drop_name}  [site {excel_site} absent du Excel]")
            continue

        payload = {**meta, "drop_id": drop_name, "date": "", "validated": False}

        out_dir = os.path.join(RESULTS_DIR, drop_name)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "drop_metadata.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        written.append(drop_name)

print(f"\n{len(written)} fichiers ecrits :")
for n in written:
    print(f"   {n}")
if skipped:
    print(f"\n{len(skipped)} drops sans correspondance :")
    for n in skipped:
        print(f"   {n}")
