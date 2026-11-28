# Hallenbad City – Belegung

**Live page: https://sazziemcsaz.github.io/hallenbad-city-tracker/**

Tracks how busy the [Hallenbad City](https://www.stadt-zuerich.ch/de/stadtleben/sport-und-erholung/sport-und-badeanlagen/hallenbaeder/city.html)
in Zürich is, through the day and over the week. The city only shows the *current* number of guests, so this
project samples it every 10 minutes during opening hours and builds the history itself.

## What the page shows

- a day × hour heatmap of the last 7 days (average occupancy in %)
- a line chart of every sample from today
- a typical-day bar chart (average per hour over everything collected)

100% = 220 guests, the capacity the city's own feed reports for this pool.

## How it works

1. A GitHub Action ([`collect-loop.yml`](.github/workflows/collect-loop.yml)) starts every hour. Each job stays alive for up to
   5h45m and takes a sample every 10 minutes while the pool is open (06:00–22:00 Zürich time), via
   [`collect_loop.py`](collect_loop.py). It is one long job rather than many short scheduled runs because GitHub's
   cron skips many runs; the hourly start only keeps the chain going. [`collect.yml`](.github/workflows/collect.yml)
   takes a single sample on demand.
2. [`collect.py`](collect.py) reads the live occupancy from the same public WebSocket feed the city's page uses
   (`wss://badi-public.crowdmonitor.ch:9591/api`) and appends one row to [`occupancy.csv`](occupancy.csv).
3. [`report.py`](report.py) turns the CSV into `index.html`, which GitHub Pages serves.

4. Once a day the collector also runs [`import_city.py`](import_city.py), which saves the city's open sensor data to
   [`backfill_city.csv`](backfill_city.csv). The report uses it to fill gaps in our own samples (outlined in the heatmap).
   The city only publishes the last few days, so older gaps can't be filled.

All scripts use only the Python standard library.

## If something breaks

- After 3 failed rounds in a row (about 30 minutes) the collector opens an issue that mentions the repo owner, and
  closes it when rounds succeed again. The job also shows as failed once it ends. It keeps trying in the meantime.
- This can't catch the case where no job is running at all. The page then shows its last sample as "delayed".
- To check that alerts reach you: Actions tab, `collect`, "Run workflow", tick `test_alert`.
- `collect_loop.py` runs `git reset --hard`, so it refuses to run outside GitHub Actions.
- Days that look closed (never more than 5 guests over 3+ hours) are left out of "typical" and "best time".
  Shortened holiday hours are not detected.

## Caveats

- The feed is not an official, documented API and could change or disappear.
- A value of 0 can mean "empty" or "closed"; the feed doesn't say which.
- Samples are taken about every 10 minutes; a dropped or delayed GitHub job can still leave gaps.

## Run it yourself

```bash
python3 collect.py                       # take one sample (add --uid SSD-7 for another pool)
python3 report.py --out report.html      # build the report from occupancy.csv
```

Occupancy data comes from the Stadt Zürich website. This is an unofficial hobby project, not affiliated with the city.
