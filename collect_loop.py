#!/usr/bin/env python3
"""Sample the pool every 10 minutes from inside ONE long-running GitHub Actions job.

Why: GitHub's cron often skips runs, and an external trigger (a Mac) sleeps. A single job that
stays alive for ~5h45m and sleeps between samples depends on neither. The workflow starts a new
job every hour, and its `concurrency` setting queues that job behind the running one, so the
chain carries on even if most cron ticks are dropped.

Each round: reset to the latest remote branch, take a sample (collect.py), rebuild the page
(report.py), commit, push. If the push is rejected (someone else pushed first) it starts the
round again from the fresh branch instead of trying to merge CSV rows.

Failures: after ALERT_AFTER bad rounds in a row it opens a GitHub issue that mentions the repo owner
(closed again once rounds succeed) and, when the job ends, marks the job as failed. It keeps
sampling and still hands over to the next job in the meantime.

It runs `git reset --hard`, so it refuses to run outside GitHub Actions unless LOOP_ALLOW_RESET=1
(only set that in a throwaway clone).

Settings (environment, mainly for testing): LOOP_INTERVAL (s, default 600),
LOOP_MAX_SECONDS (default 20700 = 5h45m, under GitHub's 6 h job limit),
LOOP_REMOTE (origin), LOOP_BRANCH (main).
"""
import json, os, signal, subprocess, sys, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
INTERVAL = int(os.environ.get("LOOP_INTERVAL", 600))
MAX_SECONDS = int(os.environ.get("LOOP_MAX_SECONDS", 5 * 3600 + 45 * 60))
REMOTE = os.environ.get("LOOP_REMOTE", "origin")
BRANCH = os.environ.get("LOOP_BRANCH", "main")
STEP_TIMEOUT = 90  # no single command may stall the loop longer than this
HANDOVER_LEAD = 20 * 60  # start the successor this long before our budget ends
ALERT_AFTER = 3  # bad rounds in a row (about 30 minutes) before raising the alarm
IMPORT_ALERT_AFTER = 12  # the city import matters less: about 2 hours of failures
ALERT_TITLE = "Tracker problem: collection is failing"
IMPORT_ALERT_TITLE = "Tracker problem: city data import is failing"
TEST_ALERT_TITLE = "Test alert from the Hallenbad tracker"
OPEN_FROM, OPEN_TO = 6, 22  # Zürich hours; the 22:00 sample is still taken
ZH = ZoneInfo("Europe/Zurich")


def sh(*cmd, timeout=STEP_TIMEOUT):
    """Run a command with a time limit. On timeout, kill its whole process group (git starts
    helper processes that would otherwise keep us waiting) and report exit code 124."""
    p = subprocess.Popen(cmd, cwd=HERE, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        msg = f"timed out after {timeout}s: {' '.join(cmd)}"
        print(msg, flush=True)
        if cmd[0] == "git":  # a killed git can leave its lock behind and block every later round
            lock = os.path.join(HERE, ".git", "index.lock")
            if os.path.exists(lock):
                os.remove(lock)
        return subprocess.CompletedProcess(cmd, 124, "", msg)


def require_safe_place():
    if not (os.environ.get("GITHUB_ACTIONS") or os.environ.get("LOOP_ALLOW_RESET")):
        sys.exit("Refusing to run: this script does `git reset --hard`, which throws away uncommitted changes.\n"
                 "It is meant for GitHub Actions. To test, use a throwaway clone and set LOOP_ALLOW_RESET=1.\n"
                 "For a single local sample, run collect.py instead.")


def open_issues(title):
    """Numbers of open issues with exactly this title, or None if GitHub couldn't be asked."""
    r = sh("gh", "issue", "list", "--state", "open", "--limit", "100", "--json", "number,title")
    if r.returncode:
        print("alert: could not list issues:", r.stderr.strip()[:200], flush=True)
        return None
    return [i["number"] for i in json.loads(r.stdout) if i["title"] == title]


def open_alert(title, reason):
    """Open one issue that mentions the owner. Returns True once an open issue exists."""
    print(f"ALERT: {reason}", flush=True)
    if not os.environ.get("GH_TOKEN"):
        return False  # not on GitHub (local test)
    found = open_issues(title)
    if found is None:
        return False
    if found:
        return True  # already reported, don't pile up duplicates
    run = "{}/{}/actions/runs/{}".format(*(os.environ.get(k, "") for k in
                                          ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")))
    body = f"@{os.environ.get('GITHUB_REPOSITORY_OWNER', '')} {reason}\n\nJob: {run}"
    r = sh("gh", "issue", "create", "--title", title, "--body", body)
    print("alert issue:", (r.stdout.strip() or r.stderr.strip())[:200], flush=True)
    return r.returncode == 0


def close_alert(title):
    """Close the issue after recovery. Returns True when nothing is left open."""
    if not os.environ.get("GH_TOKEN"):
        return True
    found = open_issues(title)
    if found is None:
        return False
    return all(sh("gh", "issue", "close", str(n), "--comment", "Working again.").returncode == 0 for n in found)


def zurich_minutes():
    n = datetime.now(ZH)
    return n.hour * 60 + n.minute


imported_on = None  # date of the last city-data import this job has pushed


import_failures = 0


def import_city_data():
    """Once a day, pull the city's open-data series so report.py can fill our gaps.
    The city keeps only ~5 days. A failure never costs a sample: the next round tries again."""
    r = sh(sys.executable, "import_city.py")
    print("city import:", (r.stdout.strip() or r.stderr.strip()[-300:]), flush=True)
    global import_failures
    if r.returncode == 0:
        import_failures = 0
        close_alert(IMPORT_ALERT_TITLE)
    else:
        import_failures += 1
        if import_failures == IMPORT_ALERT_AFTER:
            open_alert(IMPORT_ALERT_TITLE, "The city open-data import keeps failing, so new gaps aren't being filled. "
                       "The city only keeps about 5 days. Your own sampling is not affected.")
    return r.returncode == 0


def save_sample():
    """One round. Returns True if it finished cleanly: sample saved (or nothing to save) and page rebuilt."""
    require_safe_place()
    global imported_on
    for attempt in range(1, 5):
        sh("git", "fetch", "-q", REMOTE, BRANCH)
        sh("git", "reset", "-q", "--hard", f"{REMOTE}/{BRANCH}")
        r = sh(sys.executable, "collect.py", "--open-hours", f"{OPEN_FROM}-{OPEN_TO}")
        print((r.stdout.strip() or r.stderr.strip()[-300:]), flush=True)
        if r.returncode:  # feed unreachable or invalid: skip this round, try again at the next mark
            return False
        today = datetime.now(ZH).date()
        imported = imported_on != today and import_city_data()
        page = sh(sys.executable, "report.py", "--out", "index.html")
        if page.stderr.strip():  # warnings (e.g. skipped rows) or the reason it crashed
            print("report:", page.stderr.strip()[-600:], flush=True)
        healthy = page.returncode == 0  # if not, still save the sample, but count the round as failed
        sh("git", "add", "occupancy.csv", "index.html", "backfill_city.csv")
        if sh("git", "diff", "--cached", "--quiet").returncode == 0:
            return healthy  # nothing new (e.g. outside opening hours)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        sh("git", "commit", "-q", "-m", f"sample {stamp}")
        p = sh("git", "push", "-q", REMOTE, f"HEAD:{BRANCH}")
        if p.returncode == 0:
            if imported:  # only now: a rejected push throws the import away with the round
                imported_on = today
            return healthy
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


class Health:
    """Counts bad rounds in a row and raises or clears the alert."""

    def __init__(self):
        self.streak = 0
        self.job_failed = False
        self.may_be_open = True  # an earlier job may have left an alert open

    def record(self, ok):
        if ok:
            self.streak = 0
            if self.may_be_open and close_alert(ALERT_TITLE):
                self.may_be_open = False
            return
        self.streak += 1
        if self.streak >= ALERT_AFTER:
            self.job_failed = self.may_be_open = True
            if self.streak % ALERT_AFTER == 0:  # repeat the attempt in case GitHub was unreachable
                open_alert(ALERT_TITLE, f"{self.streak} rounds in a row failed. The live page may be stale. "
                                        "Check the job log for the reason.")


def main():
    require_safe_place()
    if "--test-alert" in sys.argv:
        ok = open_alert(TEST_ALERT_TITLE, "This is a test. If this reached you, tracker alerts work. "
                                          "You can close this issue.")
        sys.exit(0 if ok else 1)
    start = time.time()
    handed = False
    health = Health()
    while True:
        m = zurich_minutes()
        if OPEN_FROM * 60 <= m <= OPEN_TO * 60:
            try:
                ok = save_sample()
            except Exception as e:  # one unexpected error must not end the chain
                print(f"round crashed: {e!r}", flush=True)
                ok = False
            health.record(ok)
        # closed hours: no sampling, the job just idles so the chain never has to be restarted
        if not handed and time.time() - start > MAX_SECONDS - HANDOVER_LEAD:
            handed = hand_over()
        nxt = (time.time() // INTERVAL + 1) * INTERVAL  # next :00/:10/:20... mark
        if nxt - start > MAX_SECONDS:
            print("time budget used up, the next job takes over", flush=True)
            if health.job_failed:
                sys.exit(1)  # show this job as failed in the Actions tab
            return
        time.sleep(max(0, nxt - time.time()))


if __name__ == "__main__":
    main()
