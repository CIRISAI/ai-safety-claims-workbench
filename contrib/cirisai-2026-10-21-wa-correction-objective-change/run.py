"""Run the frozen cases in CIRISAgent CI and collect the raw log.

The evaluation itself is tools/qa_runner correction_episodes on the CIRISAgent branch named in
contribution.yaml (harness.commit); each case boots a fresh live-model agent on its own runner. This
script only (1) checks the frozen cases are public at the freeze commit with the expected sha256,
(2) dispatches the workflow with that URL + sha256 so the run can only use the frozen cases, (3) waits,
(4) downloads every per-case raw log and (5) writes one JSON-lines raw log under $WORKBENCH_RUNS with a
header line naming the run. Set M4_RUN_ID to adopt a finished run instead of dispatching one.

Needs the GitHub CLI (`gh`) authenticated with access to the harness repo's Actions.
"""

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).parent


def sh(*args, check=True):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"{' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def main():
    contribution = yaml.safe_load((HERE / "contribution.yaml").read_text(encoding="utf-8"))
    freeze = yaml.safe_load((HERE / "freeze.yaml").read_text(encoding="utf-8"))
    harness = contribution["harness"]
    repo = harness["repo"].removeprefix("https://github.com/")
    cases_bytes = (HERE / "freeze-cases.jsonl").read_bytes()
    sha = hashlib.sha256(cases_bytes).hexdigest()
    # freeze.yaml names the commit BEFORE the freeze files were committed (the method code); the cases
    # themselves are public at the freeze tag, so resolve that tag to its commit.
    tag_commit = subprocess.run(["git", "rev-parse", f"freeze/{contribution['id']}^{{commit}}"], capture_output=True, text=True)
    freeze_commit = tag_commit.stdout.strip() if tag_commit.returncode == 0 else freeze["method"]["code"]["commit"]
    cases_url = (
        f"https://raw.githubusercontent.com/CIRISAI/ai-safety-claims-workbench/{freeze_commit}/"
        f"contrib/{contribution['id']}/freeze-cases.jsonl"
    )
    runs = Path(os.environ.get("WORKBENCH_RUNS", HERE / "runs"))
    runs.mkdir(parents=True, exist_ok=True)

    run_id = os.environ.get("M4_RUN_ID")
    dispatched_at = None
    if not run_id:
        # The run must read the cases from the public freeze, not from this checkout.
        with urllib.request.urlopen(cases_url, timeout=60) as resp:  # noqa: S310 - fixed https host
            public = resp.read()
        if hashlib.sha256(public).hexdigest() != sha:
            raise SystemExit(f"{cases_url} does not match the local frozen cases (push the freeze commit first)")
        dispatched_at = dt.datetime.now(dt.timezone.utc)
        sh("gh", "workflow", "run", harness["workflow"], "-R", repo, "--ref", harness["branch"],
           "-f", f"cases_url={cases_url}", "-f", f"cases_sha256={sha}",
           "-f", f"engine_commit={harness['engine_commit']}", "-f", f"model={harness['model']}",
           "-f", f"template_id={harness['template_id']}",
           *(["-f", f"case_filter={os.environ['M4_CASE_FILTER']}"] if os.environ.get("M4_CASE_FILTER") else []))
        print(f"dispatched {harness['workflow']} on {repo}@{harness['branch']} with cases {sha[:12]}", flush=True)
        for _ in range(30):
            time.sleep(10)
            rows = json.loads(sh("gh", "run", "list", "-R", repo, "--workflow", harness["workflow"],
                                 "--branch", harness["branch"], "--limit", "5",
                                 "--json", "databaseId,createdAt,status,headSha"))
            rows = [r for r in rows if dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) >= dispatched_at - dt.timedelta(seconds=30)]
            if rows:
                run_id = str(rows[0]["databaseId"])
                break
        if not run_id:
            raise SystemExit("dispatched, but no run appeared within five minutes")
    print(f"run {run_id}: https://github.com/{repo}/actions/runs/{run_id}", flush=True)

    while True:
        info = json.loads(sh("gh", "run", "view", run_id, "-R", repo, "--json", "status,conclusion,headSha,createdAt,updatedAt,url"))
        if info["status"] == "completed":
            break
        print(f"  {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} status={info['status']}", flush=True)
        time.sleep(120)
    if info["headSha"] != harness["commit"]:
        raise SystemExit(f"run {run_id} ran harness commit {info['headSha']}, contribution names {harness['commit']}")

    with tempfile.TemporaryDirectory() as tmp:
        sh("gh", "run", "download", run_id, "-R", repo, "-p", "m4-raw-*", "-D", tmp)
        files = sorted(Path(tmp).rglob("*.jsonl"))
        if not files:
            raise SystemExit(f"run {run_id} produced no m4-raw-* artifacts")
        out = runs / f"run-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{run_id}.jsonl"
        header = {
            "event": "run", "t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id, "run_url": info["url"], "conclusion": info["conclusion"],
            "harness_repo": harness["repo"], "harness_commit": info["headSha"], "engine_commit": harness["engine_commit"],
            "model": harness["model"], "template_id": harness["template_id"],
            "cases_url": cases_url, "cases_sha256": sha, "dispatched_at": dispatched_at.isoformat() if dispatched_at else None,
            "case_files": [f.name for f in files],
        }
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            for f in files:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        fh.write(line.rstrip("\n") + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
