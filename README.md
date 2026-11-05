# Hallenbad City – Belegung

**Live page: https://sazziemcsaz.github.io/hallenbad-city-tracker/**

Tracks how busy the [Hallenbad City](https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/city.html)
in Zürich is, through the day and over the week. The city only shows the *current* number of guests, so this
project samples it every 10 minutes and builds the history itself.

## What the page shows

- a day × hour heatmap of the last 7 days (average occupancy in %)
- a line chart of every sample from today
- a typical-day bar chart (average per hour over everything collected)

100% = 220 guests, the capacity the city's own feed reports for this pool.

## How it works

1. A scheduled GitHub Action ([`collect.yml`](.github/workflows/collect.yml)) runs every 10 minutes.
2. [`collect.py`](collect.py) reads the live occupancy from the same public WebSocket feed the city's page uses
   (`wss://badi-public.crowdmonitor.ch:9591/api`) and appends one row to [`occupancy.csv`](occupancy.csv).
3. [`report.py`](report.py) turns the CSV into `index.html`, which GitHub Pages serves.

Both scripts use only the Python standard library.

## Caveats

- The feed is not an official, documented API and could change or disappear.
- A value of 0 can mean "empty" or "closed"; the feed doesn't say which.
- GitHub's scheduler can start runs a few minutes late, so samples aren't exactly 10 minutes apart.

## Run it yourself

```bash
python3 collect.py                       # take one sample (add --uid SSD-7 for another pool)
python3 report.py --out report.html      # build the report from occupancy.csv
```

Occupancy data comes from the Stadt Zürich website. This is an unofficial hobby project, not affiliated with the city.
