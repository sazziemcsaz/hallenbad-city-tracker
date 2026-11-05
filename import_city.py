#!/usr/bin/env python3
"""Import Hallenbad City history from the city's open-data series into backfill_city.csv.

Source: "Datenreihe «Anzahl der Badegäste»" on data.stadt-zuerich.ch (licence CC0).
Sensor data in 5-minute slots, Zurich local time, only the last ~5 days are published,
so re-running this keeps what is already in backfill_city.csv and adds/updates the rest.
Only slots inside opening hours (06:00-22:00) are kept. Stdlib only.

Usage: python3 import_city.py [--cap 220]
"""
import argparse, csv, io, os, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://data.stadt-zuerich.ch/dataset/ssd_spo_badi_besuch/download/badi_besuch.csv"
FIELDS = ["timestamp", "uid", "name", "current", "max", "pct"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=220, help="capacity used for the percentage")
    ap.add_argument("--out", default=os.path.join(HERE, "backfill_city.csv"))
    args = ap.parse_args()

    with urllib.request.urlopen(URL, timeout=60) as r:
        text = r.read().decode("utf-8")

    rows = {}
    if os.path.exists(args.out):  # keep earlier imports; the city only publishes ~5 days
        with open(args.out, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["timestamp"]] = [r[k] for k in FIELDS]

    zone = ZoneInfo("Europe/Zurich")
    added = 0
    for r in csv.DictReader(io.StringIO(text)):
        if r["LocationName"] != "Hallenbad City" or r["OccupancyMax"] == "":
            continue
        t = datetime.fromisoformat(r["Datetime"]).replace(tzinfo=zone)  # file is local time
        if not 6 * 60 <= t.hour * 60 + t.minute <= 22 * 60:
            continue
        cur = int(float(r["OccupancyMax"]))
        key = t.isoformat(timespec="seconds")
        added += key not in rows
        rows[key] = [key, "OD-SENSOR", "Hallenbad City", cur, args.cap, round(100 * cur / args.cap, 1)]

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for k in sorted(rows):
            w.writerow(rows[k])
    print(f"{len(rows)} rows in {args.out} ({added} new)")


if __name__ == "__main__":
    main()
