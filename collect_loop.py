#!/usr/bin/env python3
"""Sample the pool every 10 minutes from inside ONE long-running GitHub Actions job.

Why: GitHub's cron often skips runs, and an external trigger (a Mac) sleeps. A single job that
stays alive for ~5h45m and sleeps between samples depends on neither. The workflow starts a new
job every hour, and its `concurrency` setting queues that job behind the running one, so the
chain carries on even if most cron ticks are dropped.

Each round: reset to the latest remote branch, take a sample (collect.py), rebuild the page
(report.py), commit, push. If the push is rejected (someone else pushed first) it starts the
round again from the fresh branch instead of trying to merge CSV rows.

Settings (environment, mainly for testing): LOOP_INTERVAL (s, default 600),
LOOP_MAX_SECONDS (default 20700 = 5h45m, under GitHub's 6 h job limit),
LOOP_REMOTE (origin), LOOP_BRANCH (main).
"""
import os, subprocess, sys, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
INTERVAL = int(os.environ.get("LOOP_INTERVAL", 600))
MAX_SECONDS = int(os.environ.get("LOOP_MAX_SECONDS", 5 * 3600 + 45 * 60))
REMOTE = os.environ.get("LOOP_REMOTE", "origin")
BRANCH = os.environ.get("LOOP_BRANCH", "main")
HANDOVER_LEAD = 20 * 60  # start the successor this long before our budget ends
OPEN_FROM, OPEN_TO = 6, 22  # Zürich hours; the 22:00 sample is still taken
ZH = ZoneInfo("Europe/Zurich")


def sh(*cmd):
    return subprocess.run(cmd, cwd=HERE, text=True, capture_output=True)


def zurich_minutes():
    n = datetime.now(ZH)
    return n.hour * 60 + n.minute


def save_sample():
    """One round. Returns True if the round finished cleanly (sample saved or nothing to save)."""
    for attempt in range(1, 5):
        sh("git", "fetch", "-q", REMOTE, BRANCH)
        sh("git", "reset", "-q", "--hard", f"{REMOTE}/{BRANCH}")
        r = sh(sys.executable, "collect.py", "--open-hours", f"{OPEN_FROM}-{OPEN_TO}")
        print((r.stdout.strip() or r.stderr.strip()[-300:]), flush=True)
        if r.returncode:  # feed unreachable or invalid: skip this round, try again at the next mark
            return False
        sh(sys.executable, "report.py", "--out", "index.html")
        sh("git", "add", "occupancy.csv", "index.html")
        if sh("git", "diff", "--cached", "--quiet").returncode == 0:
            return True  # nothing new (e.g. outside opening hours)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        sh("git", "commit", "-q", "-m", f"sample {stamp}")
        p = sh("git", "push", "-q", REMOTE, f"HEAD:{BRANCH}")
        if p.returncode == 0:
            return True
        print(f"push rejected (attempt {attempt}), redoing the round: {p.stderr.strip()[:200]}", flush=True)
        time.sleep(2 * attempt)
    return False


def hand_over():
    """Start the next job ourselves. GitHub's cron is too unreliable to carry the chain.
    A workflow_dispatch started with the job's own token is allowed (unlike push/schedule events);
    `concurrency` then holds the new job in the queue until this one ends."""
    if not os.environ.get("GH_TOKEN"):
        return False  # not on GitHub (e.g. local test)
    r = sh("gh", "workflow", "run", "collect-loop.yml", "--ref", BRANCH)
    print("hand-over:", (r.stdout.strip() or r.stderr.strip())[:200], flush=True)
    return r.returncode == 0


def main():
    start = time.time()
    handed = False
    while True:
        m = zurich_minutes()
        if OPEN_FROM * 60 <= m <= OPEN_TO * 60:
            save_sample()
        # closed hours: no sampling, the job just idles so the chain never has to be restarted
        if not handed and time.time() - start > MAX_SECONDS - HANDOVER_LEAD:
            handed = hand_over()
        nxt = (time.time() // INTERVAL + 1) * INTERVAL  # next :00/:10/:20... mark
        if nxt - start > MAX_SECONDS:
            print("time budget used up, the next job takes over", flush=True)
            return
        time.sleep(max(0, nxt - time.time()))


if __name__ == "__main__":
    main()
