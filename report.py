#!/usr/bin/env python3
"""Turn occupancy.csv into report.html: a day x hour heatmap of the last 7 days.

Each cell = average occupancy (%) of all samples taken in that hour.
Grey cells = no sample. Hover a cell for the average head count and sample count.

Usage: python3 report.py [--csv occupancy.csv] [--out report.html] [--days 7]
"""
import argparse, csv, html, os
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["timestamp"]), int(r["current"]), int(r["max"]), r["name"]))
    return rows


def colour(p):
    # 0% pale -> 100% deep blue; >100% turns red (page allows over-capacity)
    if p > 100:
        return "hsl(5 70% 45%)", "#fff"
    l = 96 - 58 * (p / 100)
    return f"hsl(210 75% {l:.0f}%)", ("#fff" if l < 58 else "#123")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "occupancy.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "report.html"))
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()

    rows = load(a.csv)
    if not rows:
        raise SystemExit("no data yet")
    name = rows[0][3]
    last = max(r[0] for r in rows)
    first_day = (last - timedelta(days=a.days - 1)).date()
    days = [first_day + timedelta(days=i) for i in range(a.days)]

    cells = defaultdict(list)  # (date, hour) -> [(current, max)]
    for ts, cur, mx, _ in rows:
        if ts.date() >= first_day:
            cells[(ts.date(), ts.hour)].append((cur, mx))

    hours = range(24)
    # trim empty leading/trailing hours so the table stays readable
    used = [h for h in hours if any((d, h) in cells for d in days)]
    # always show at least 06-22 so the grid looks right even with little data
    hours = range(min(6, *used), max(22, *used) + 1) if used else range(6, 23)

    out = ['<table><thead><tr><th class="d"></th>' + "".join(f"<th>{h:02d}</th>" for h in hours) + "</tr></thead><tbody>"]
    for d in days:
        out.append(f"<tr><th class='d'>{DAYS_DE[d.weekday()]} {d.strftime('%d.%m.')}</th>")
        for h in hours:
            s = cells.get((d, h))
            if not s:
                out.append("<td class='none'></td>")
                continue
            pct = sum(100 * c / m for c, m in s) / len(s)
            avg = sum(c for c, _ in s) / len(s)
            bg, fg = colour(pct)
            tip = f"{DAYS_DE[d.weekday()]} {d.strftime('%d.%m.')} {h:02d}:00 · ø {avg:.0f} Gäste · {len(s)} Messung(en)"
            out.append(f"<td style='background:{bg};color:{fg}' title='{html.escape(tip)}'>{pct:.0f}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")

    cap = rows[-1][2]

    # "Heute": every sample of the latest day as a line (x = time, y = guests)
    today = sorted((r for r in rows if r[0].date() == last.date()), key=lambda r: r[0])
    W, H, L, R, T, B = 1000, 280, 104, 2, 14, 30  # L/R match the heatmap tile area
    x0, x1 = hours.start, hours.stop  # hour axis matches heatmap columns
    ymax = max(cap, max(c for _, c, _, _ in today))
    X = lambda ts: L + (ts.hour + ts.minute / 60 - x0) / (x1 - x0) * (W - L - R)
    Y = lambda c: T + (1 - c / ymax) * (H - T - B)
    svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Verlauf heute" class="today">']
    for p in (0, 25, 50, 75, 100):
        y = Y(cap * p / 100)
        svg.append(f'<line x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="0" y="{y+4:.1f}" text-anchor="start">{p}% · {round(cap*p/100)}</text>')
    for h in range(x0, x1):  # label centred over each hour column, like the heatmap
        x = L + (h + 0.5 - x0) / (x1 - x0) * (W - L - R)
        svg.append(f'<text x="{x:.1f}" y="{H-8}" text-anchor="middle">{h:02d}</text>')
    pts = " ".join(f"{X(ts):.1f},{Y(c):.1f}" for ts, c, _, _ in today)
    svg.append(f'<polyline points="{pts}" class="ln"/>')
    for ts, c, m, _ in today:
        tip = f"{ts.strftime('%H:%M')} · {c} Gäste · {100*c/m:.0f}%"
        svg.append(f'<circle cx="{X(ts):.1f}" cy="{Y(c):.1f}" r="3.5" class="pt"><title>{tip}</title></circle>')
    svg.append("</svg>")
    today_svg = "".join(svg)
    today_title = f"Heute, {DAYS_DE[last.weekday()]} {last.strftime('%d.%m.')} – alle Messungen ({len(today)})"

    # typical hour-of-day profile (average of all samples per hour) as bars with a y axis
    by_h = defaultdict(list)
    for ts, cur, mx, _ in rows:
        by_h[ts.hour].append((cur, 100 * cur / mx))
    PH = 220
    py = lambda c: T + (1 - c / ymax) * (PH - T - B)
    n = x1 - x0
    cw = (W - L - R) / n
    ps = [f'<svg viewBox="0 0 {W} {PH}" role="img" aria-label="Typischer Tagesverlauf" class="today">']
    for p in (0, 25, 50, 75, 100):
        y = py(cap * p / 100)
        ps.append(f'<line x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                  f'<text x="0" y="{y+4:.1f}" text-anchor="start">{p}% · {round(cap*p/100)}</text>')
    for k, h in enumerate(range(x0, x1)):
        cx = L + (k + 0.5) * cw
        ps.append(f'<text x="{cx:.1f}" y="{PH-8}" text-anchor="middle">{h:02d}</text>')
        v = by_h.get(h)
        if v:
            avg = sum(c for c, _ in v) / len(v)
            tip = f"{h:02d}:00 · ø {avg:.0f} Gäste · {sum(p for _, p in v)/len(v):.0f}% · {len(v)} Messung(en)"
            ps.append(f'<rect x="{L + k*cw + 1:.1f}" y="{py(avg):.1f}" width="{cw-2:.1f}" height="{PH-B-py(avg):.1f}" '
                      f'rx="3" class="col"><title>{tip}</title></rect>')
    ps.append("</svg>")
    prof = "".join(ps)
    labels = {0: "leer", 25: "ruhig", 50: "belebt", 75: "voll", 100: "Maximum"}
    key = "".join(
        (lambda bg, fg: f"<span class='k'><i style='background:{bg}'></i><b>{p}%</b> = {round(cap * p / 100)} Gäste"
                        f"<em>{labels[p]}</em></span>")(colour(p)[0], colour(p)[1])
        for p in (0, 25, 50, 75, 100)
    )

    page = f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="600"><title>{html.escape(name)} Belegung</title>
<style>
:root{{--bg:#fff;--fg:#1a2530;--mut:#6b7885;--none:#eceff2}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12171c;--fg:#e4e9ee;--mut:#8c98a4;--none:#222a31}}}}
body{{background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1000px;margin-inline:auto}}
h1{{font-size:22px;margin:0 0 4px}}p.s{{color:var(--mut);margin:0 0 20px}}
.wrap{{overflow-x:auto}}table{{width:100%;table-layout:fixed;border-collapse:separate;border-spacing:2px;font-variant-numeric:tabular-nums}}
th{{font-weight:500;font-size:12px;color:var(--mut);padding:2px 4px}}th.d{{width:100px;text-align:left;white-space:nowrap;padding:2px 0}}
td{{height:30px;text-align:center;font-size:12px;border-radius:4px}}td.none{{background:var(--none)}}
h2{{font-size:16px;margin:28px 0 8px}}
.key{{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:14px;font-size:13px}}
.key .k{{display:flex;align-items:center;gap:6px}}.key i{{width:16px;height:16px;border-radius:4px;display:inline-block}}
.key em{{color:var(--mut);font-style:normal}}.key em::before{{content:"· "}}
.today{{width:100%;height:auto;display:block}}.today text{{fill:var(--mut);font-size:12px}}
.today .grid{{stroke:var(--none);stroke-width:1}}.today .ln{{fill:none;stroke:hsl(210 75% 50%);stroke-width:2.5;stroke-linejoin:round}}
.today .col{{fill:hsl(210 75% 50%)}}
.today .pt{{fill:hsl(210 75% 50%);stroke:var(--bg);stroke-width:1.5}}
.leg{{margin-top:10px;color:var(--mut);font-size:12px}}
</style></head><body>
<h1>{html.escape(name)} – Belegung</h1>
<p class="s">Zeitraum {days[0].strftime('%d.%m.')}–{days[-1].strftime('%d.%m.%Y')} · {len(rows)} Messungen · Wert = Auslastung in % (ø pro Stunde), letzte Messung {last.strftime('%d.%m. %H:%M')}</p>
<div class="wrap">{''.join(out)}</div>
<div class="key">{key}</div>
<p class="leg">Hell = leer, dunkelblau = voll, rot = über Kapazität, grau = keine Messung. Ein 0-Wert kann «leer» oder «geschlossen» heissen.</p>
<h2>{today_title}</h2>
{today_svg}
<h2>Typischer Tagesverlauf (ø aller Messungen)</h2>
{prof}
</body></html>"""
    with open(a.out, "w") as f:
        f.write(page)
    print(f"wrote {a.out} ({len(rows)} samples)")


if __name__ == "__main__":
    main()
