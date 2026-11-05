#!/usr/bin/env python3
"""Turn occupancy.csv into a single HTML page with three views:

  1. Live now      - latest head count, today's curve vs. a typical day, quick stats
  2. Last 7 days   - day x hour heatmap (average occupancy per hour) + typical-day bars
  3. Best time     - preview of the quietest two hours per weekday (needs a few weeks of data)

Usage: python3 report.py [--csv occupancy.csv] [--out report.html] [--days 7]
"""
import argparse, csv, html, os
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LEVELS = {0: "empty", 25: "quiet", 50: "busy", 75: "full", 100: "at capacity"}
OPEN_FROM, OPEN_TO = 6, 22  # opening hours (Zurich time)


def load(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append((datetime.fromisoformat(r["timestamp"]), int(r["current"]), int(r["max"]), r["name"]))
    return sorted(rows, key=lambda r: r[0])


def word(p):
    """Same quarter steps as the legend, cut at the midpoints."""
    return ("empty" if p < 12.5 else "quiet" if p < 37.5 else "busy" if p < 62.5
            else "full" if p < 87.5 else "at capacity")


def colour(p):
    if p > 100:  # the city's feed allows over-capacity
        return "hsl(5 70% 45%)", "#fff"
    l = 96 - 58 * (p / 100)
    return f"hsl(210 75% {l:.0f}%)", ("#fff" if l < 58 else "#123")


def mean(v):
    return sum(v) / len(v)


CSS = """
:root{--bg:#fff;--fg:#1a2530;--mut:#6b7885;--none:#eceff2;--card:#f4f6f8;--line:hsl(210 75% 50%);--warn:#b7791f}
@media(prefers-color-scheme:dark){:root{--bg:#12171c;--fg:#e4e9ee;--mut:#8c98a4;--none:#222a31;--card:#1a2128;--warn:#e0a63a}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif;margin:0 auto;padding:24px 16px 48px;max-width:1000px}
h1{font-size:22px;margin:0 0 4px}p.s{color:var(--mut);margin:0 0 24px}
h2{font-size:16px;margin:36px 0 10px}h2 small{font-weight:400;color:var(--mut);font-size:13px;margin-left:6px}
.mut{color:var(--mut);font-size:13px}
.card{background:var(--card);border-radius:12px;padding:14px 16px}
.live{display:grid;grid-template-columns:minmax(0,230px) minmax(0,1fr);gap:14px}
.hero{display:flex;flex-direction:column;justify-content:space-between;gap:10px}
.big{font:500 56px/1.05 "Iowan Old Style",Georgia,"Times New Roman",serif;font-variant-numeric:tabular-nums lining-nums}
.meter{height:8px;border-radius:4px;background:var(--none)}.meter i{display:block;height:8px;border-radius:4px;background:var(--line)}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px}
.stat b{display:block;font-weight:500;font-size:16px;margin-top:2px}
.stat.warn{outline:1.5px solid var(--warn)}.stat.warn #ago::after{content:" - delayed";color:var(--warn)}
.lg{display:flex;gap:14px;font-size:12px;color:var(--mut);margin-bottom:4px}
.lg i{display:inline-block;width:14px;height:0;border-top:2px solid var(--line);vertical-align:middle;margin-right:5px}
.lg i.d{border-top:2px dashed var(--mut)}
.wrap{overflow-x:auto}
table{width:100%;table-layout:fixed;border-collapse:separate;border-spacing:2px;font-variant-numeric:tabular-nums}
th{font-weight:500;font-size:12px;color:var(--mut);padding:2px 4px}th.d{width:100px;text-align:left;white-space:nowrap;padding:2px 0}
td{height:30px;text-align:center;font-size:12px;border-radius:4px}td.none{background:var(--none)}
.key{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:14px;font-size:13px}
.key .k{display:flex;align-items:center;gap:6px}.key i{width:16px;height:16px;border-radius:4px;display:inline-block}
.key em{color:var(--mut);font-style:normal}.key em::before{content:"- "}
.leg{margin-top:10px;color:var(--mut);font-size:12px}
.chart{width:100%;height:auto;display:block}.chart text{fill:var(--mut);font-size:12px}
.chart .grid{stroke:var(--none);stroke-width:1}
.chart .ln{fill:none;stroke:var(--line);stroke-width:2.5;stroke-linejoin:round}
.chart .ty{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:4 3}
.chart .pt{fill:var(--line);stroke:var(--bg);stroke-width:1.5}.chart .col{fill:var(--line)}
.verdict{display:flex;gap:12px;align-items:center;margin-bottom:12px}
.verdict .t{font-size:16px;font-weight:500}
.best{display:grid;gap:6px;margin-top:6px}
.best .r{display:flex;align-items:center;gap:10px;font-size:13px}
.best .d{width:32px}.best .w{width:100px;font-variant-numeric:tabular-nums}
.best .bar{flex:1;height:10px;border-radius:5px;background:var(--card)}.best .bar i{display:block;height:10px;border-radius:5px;background:var(--line)}
.best .v{width:92px;text-align:right;color:var(--mut);font-size:12px}.best .v.top{color:var(--line)}
.note{background:var(--card);border-radius:8px;padding:8px 12px;font-size:13px;color:var(--mut);margin-bottom:12px}
@media(max-width:640px){.live{grid-template-columns:1fr}.stats{grid-template-columns:1fr}.big{font-size:48px}}
"""

AGO_JS = """
(function(){var el=document.getElementById('ago');if(!el)return;var t=Date.parse(el.dataset.ts);
function up(){var m=Math.max(0,Math.round((Date.now()-t)/60000));
el.textContent=m<1?'just now':m<60?m+' min ago':Math.floor(m/60)+' h '+(m%60)+' min ago';
var h=+new Date().toLocaleString('en-GB',{timeZone:'Europe/Zurich',hour:'2-digit',hour12:false})%24;
el.closest('.stat').classList.toggle('warn',h>=__FROM__&&h<__TO__&&m>30);}
up();setInterval(up,30000);})();
// reload every 5 min with a throwaway query string so the browser cache (max-age=600) is bypassed
setTimeout(function(){location.replace(location.pathname+'?r='+Date.now());},300000);
""".replace("__FROM__", str(OPEN_FROM)).replace("__TO__", str(OPEN_TO))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "occupancy.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "report.html"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--backfill", default=os.path.join(HERE, "backfill_city.csv"),
                    help="city open-data history; used only before our own first sample")
    a = ap.parse_args()

    own = load(a.csv)
    if not own:
        raise SystemExit("no data yet")
    city = []
    if os.path.exists(a.backfill):  # our own samples win from their first timestamp on
        city = [r for r in load(a.backfill) if r[0] < own[0][0]]
    rows = sorted(city + own, key=lambda r: r[0])
    name = rows[0][3]
    cap = rows[-1][2]
    last_ts, last_cur = rows[-1][0], rows[-1][1]
    last_pct = 100 * last_cur / cap
    first_day = (last_ts - timedelta(days=a.days - 1)).date()
    days = [first_day + timedelta(days=i) for i in range(a.days)]
    n_days = len({r[0].date() for r in rows})

    # ---------- shared hour axis (06-22 at least) ----------
    cells = defaultdict(list)  # (date, hour) -> [(current, max)]
    for ts, cur, mx, _ in rows:
        if ts.date() >= first_day:
            cells[(ts.date(), ts.hour)].append((cur, mx))
    used = [h for (_, h) in cells]
    hours = range(min(OPEN_FROM, *used), max(OPEN_TO, *used) + 1) if used else range(OPEN_FROM, OPEN_TO + 1)
    x0, x1 = hours.start, hours.stop

    # ---------- 1. live now ----------
    today = [r for r in rows if r[0].date() == last_ts.date()]
    other = [r for r in rows if r[0].date() != last_ts.date()]
    ymax = max(cap, max(r[1] for r in today))
    W, H, L, R, T, B = 600, 200, 34, 6, 10, 22
    X = lambda t: L + (t - x0) / (x1 - x0) * (W - L - R)
    Y = lambda c: T + (1 - c / ymax) * (H - T - B)
    sv = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Today\'s occupancy">']
    for p in (0, 50, 100):
        sv.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{Y(cap*p/100):.1f}" y2="{Y(cap*p/100):.1f}"/>'
                  f'<text x="0" y="{Y(cap*p/100)+4:.1f}">{round(cap*p/100)}</text>')
    for h in range(x0, x1 + 1, 4):
        sv.append(f'<text x="{X(h):.1f}" y="{H-5}" text-anchor="middle">{h:02d}</text>')
    by_hour_other = defaultdict(list)
    for ts, cur, _, _ in other:
        by_hour_other[ts.hour].append(cur)
    typical = [(h + 0.5, mean(v)) for h, v in sorted(by_hour_other.items())]
    if len(typical) >= 2:
        sv.append('<polyline class="ty" points="' + " ".join(f"{X(t):.1f},{Y(c):.1f}" for t, c in typical) + '"/>')
    pts = [(ts.hour + ts.minute / 60, cur, ts) for ts, cur, _, _ in today]
    sv.append('<polyline class="ln" points="' + " ".join(f"{X(t):.1f},{Y(c):.1f}" for t, c, _ in pts) + '"/>')
    for t, c, ts in pts:
        sv.append(f'<circle class="pt" r="3.5" cx="{X(t):.1f}" cy="{Y(c):.1f}"><title>{ts:%H:%M} - {c} guests ({100*c/cap:.0f}%)</title></circle>')
    sv.append("</svg>")
    typ_leg = '<span><i class="d"></i>typical</span>' if len(typical) >= 2 else ""

    peak = max(today, key=lambda r: r[1])
    low = min(today, key=lambda r: r[1])
    live = f"""
<div class="live">
  <div class="card hero">
    <div class="mut">Latest sample, {last_ts:%H:%M}</div>
    <div class="big">{last_cur}</div>
    <div>
      <div class="mut" style="margin-bottom:6px">guests - {last_pct:.0f}% of {cap} - {word(last_pct)}</div>
      <div class="meter"><i style="width:{min(100,last_pct):.0f}%"></i></div>
    </div>
  </div>
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <b style="font-weight:500">Today, {DAYS[last_ts.weekday()]} {last_ts:%d %b}</b>
      <span class="lg"><span><i></i>today</span>{typ_leg}</span>
    </div>
    {''.join(sv)}
  </div>
</div>
<div class="stats">
  <div class="card stat"><span class="mut">Peak today</span><b>{peak[0]:%H:%M} - {peak[1]} guests</b></div>
  <div class="card stat"><span class="mut">Quietest so far today</span><b>{low[0]:%H:%M} - {low[1]} guests</b></div>
  <div class="card stat"><span class="mut">Last sample</span><b id="ago" data-ts="{last_ts.isoformat()}">{last_ts:%H:%M}</b></div>
</div>"""

    # ---------- 2. heatmap + typical day ----------
    t = ['<table><thead><tr><th class="d"></th>' + "".join(f"<th>{h:02d}</th>" for h in hours) + "</tr></thead><tbody>"]
    for d in days:
        t.append(f"<tr><th class='d'>{DAYS[d.weekday()]} {d:%d.%m.}</th>")
        for h in hours:
            s = cells.get((d, h))
            if not s:
                t.append("<td class='none'></td>")
                continue
            pct = mean([100 * c / m for c, m in s])
            bg, fg = colour(pct)
            tip = f"{DAYS[d.weekday()]} {d:%d.%m.} {h:02d}:00 - avg {mean([c for c, _ in s]):.0f} guests - {len(s)} sample(s)"
            t.append(f"<td style='background:{bg};color:{fg}' title='{html.escape(tip)}'>{pct:.0f}</td>")
        t.append("</tr>")
    t.append("</tbody></table>")
    key = "".join(
        f"<span class='k'><i style='background:{colour(p)[0]}'></i><b>{p}%</b> = {round(cap*p/100)} guests<em>{LEVELS[p]}</em></span>"
        for p in LEVELS)

    by_h = defaultdict(list)
    for ts, cur, _, _ in rows:
        by_h[ts.hour].append((cur, 100 * cur / cap))
    PW, PH, PL, PR = 1000, 220, 104, 2  # left edge matches the heatmap tile area
    cw = (PW - PL - PR) / (x1 - x0)
    py = lambda c: 10 + (1 - c / ymax) * (PH - 10 - 30)
    ps = [f'<svg viewBox="0 0 {PW} {PH}" class="chart" role="img" aria-label="Typical day">']
    for p in (0, 25, 50, 75, 100):
        y = py(cap * p / 100)
        ps.append(f'<line class="grid" x1="{PL}" x2="{PW-PR}" y1="{y:.1f}" y2="{y:.1f}"/>'
                  f'<text x="0" y="{y+4:.1f}">{p}% - {round(cap*p/100)}</text>')
    for k, h in enumerate(range(x0, x1)):
        ps.append(f'<text x="{PL+(k+0.5)*cw:.1f}" y="{PH-8}" text-anchor="middle">{h:02d}</text>')
        v = by_h.get(h)
        if v:
            avg = mean([c for c, _ in v])
            tip = f"{h:02d}:00 - avg {avg:.0f} guests - {mean([p for _, p in v]):.0f}% - {len(v)} sample(s)"
            ps.append(f'<rect class="col" rx="3" x="{PL+k*cw+1:.1f}" y="{py(avg):.1f}" width="{cw-2:.1f}" '
                      f'height="{PH-30-py(avg):.1f}"><title>{tip}</title></rect>')
    ps.append("</svg>")

    # ---------- 3. best time (preview) ----------
    wh = defaultdict(list)  # (weekday, hour) -> [pct]
    for ts, cur, _, _ in rows:
        wh[(ts.weekday(), ts.hour)].append(100 * cur / cap)
    wh_other = defaultdict(list)
    for ts, cur, _, _ in other:
        wh_other[(ts.weekday(), ts.hour)].append(100 * cur / cap)
    tip = "Not enough data for a forecast yet."
    for h in range(last_ts.hour + 1, OPEN_TO):
        v = wh_other.get((last_ts.weekday(), h))
        if v and mean(v) <= last_pct - 10:
            tip = f"On {DAYS[last_ts.weekday()]}s it's usually quieter from {h:02d}:00 (around {mean(v):.0f}%)."
            break
    wins = []
    for wd in range(7):
        best = None
        for s in range(OPEN_FROM, OPEN_TO - 1):
            p1, p2 = wh.get((wd, s)), wh.get((wd, s + 1))
            if p1 and p2:
                m = (mean(p1) + mean(p2)) / 2
                if best is None or m < best[1]:
                    best = (s, m)
        wins.append(best)
    top = min((w[1] for w in wins if w), default=None)
    rows_html = []
    for wd, w in enumerate(wins):
        if w is None:
            rows_html.append(f'<div class="r"><span class="d">{DAYS[wd]}</span><span class="w mut">no data yet</span>'
                             f'<div class="bar"></div><span class="v"></span></div>')
        else:
            s, m = w
            is_top = m == top
            rows_html.append(
                f'<div class="r"><span class="d">{DAYS[wd]}</span><span class="w">{s:02d}-{s+2:02d}h</span>'
                f'<div class="bar"><i style="width:{min(100,m):.0f}%"></i></div>'
                f'<span class="v{" top" if is_top else ""}">{m:.0f}%{" - best" if is_top else ""}</span></div>')
    best_html = f"""
<div class="note">Preview: based on {n_days} day{'s' if n_days != 1 else ''} of data. It only becomes meaningful after a few weeks.</div>
<div class="card">
  <div class="verdict">
    <div><div class="t">Right now it's {word(last_pct)} ({last_pct:.0f}%)</div><div class="mut">{tip}</div></div>
  </div>
  <div class="mut">Quietest two hours per weekday (average of all samples)</div>
  <div class="best">{''.join(rows_html)}</div>
</div>"""

    city_note = (f'<p class="leg">Before {own[0][0]:%d %b %H:%M} the values come from the city\'s open-data sensor series '
                 f'(Stadt Zürich, CC0) and may read higher than the live feed; from then on they are our own samples.</p>'
                 if city else "")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} occupancy</title>
<style>{CSS}</style></head><body>
<h1>{html.escape(name)} - occupancy</h1>
<p class="s">Zurich time - {len(own)} own samples{f" + {len(city)} city sensor readings" if city else ""} since {rows[0][0]:%d %b %Y}, last sample {last_ts:%d %b %H:%M}</p>

<h2>Live now</h2>
{live}

<h2>Last {a.days} days <small>average occupancy per hour, in %</small></h2>
<div class="wrap">{''.join(t)}</div>
<div class="key">{key}</div>
<p class="leg">Light = empty, dark blue = full, red = over capacity, grey = no sample. A 0 can mean empty or closed.</p>
{city_note}
<h2>Typical day <small>average of all samples</small></h2>
{''.join(ps)}

<h2>Best time to go <small>preview</small></h2>
{best_html}
<script>{AGO_JS}</script>
</body></html>"""
    with open(a.out, "w") as f:
        f.write(page)
    print(f"wrote {a.out} ({len(rows)} samples)")


if __name__ == "__main__":
    main()
