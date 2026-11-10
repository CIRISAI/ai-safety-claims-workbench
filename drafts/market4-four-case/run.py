"""Run the frozen cases in CI and collect the raw log.

The evaluation is tools/qa_runner correction_episodes on the CIRISAgent commit named in contribution.yaml
(harness.commit); each case boots a fresh live-model agent on its own runner. This script only:
  1. refuses while contribution.yaml still holds a <<FILL: ...>> placeholder;
  2. checks the frozen cases are public at the freeze tag's commit with the same sha256 as the committed file
     (and equal to harness.cases_sha256 when that optional pin is set);
  3. dispatches the workflow at harness.dispatch_ref with every pin from contribution.yaml (harness and engine
     commits, model, template, constraints URL + sha256, provider order, seed), so the run can only use them;
  4. waits; checks the run's manifest names exactly those pins and that it ran the dispatch tag's workflow commit;
  5. downloads every per-case raw log and writes one JSON-lines raw log under $WORKBENCH_RUNS with a header line.
Set M4_RUN_ID to adopt a finished run instead of dispatching; M4_CASE_FILTER to run a subset. Nothing is hard-coded:
repositories, tag, workflow, artifact names and pins all come from contribution.yaml.

Needs the GitHub CLI (`gh`) authenticated with access to the dispatch repo's Actions.
"""

import datetime as dt
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).parent
PINNED = ("commit", "engine_commit", "dispatch_repo", "dispatch_ref", "workflow", "model", "template_id",
          "constraints_url", "constraints_sha256", "cases_repo", "cases_path")


def sh(*args, check=True):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"{' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def unfilled(obj, path=""):
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in unfilled(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in unfilled(v, f"{path}[{i}]")]
    return [path] if isinstance(obj, str) and "<<FILL" in obj else []


def pins(contribution):
    holes = unfilled(contribution)
    if holes:
        raise SystemExit(f"contribution.yaml still has placeholders: {holes}")
    h = contribution["harness"]
    missing = [k for k in PINNED if not str(h.get(k) or "").strip()]
    if missing:
        raise SystemExit(f"contribution.yaml harness lacks {missing}")
    return h


def main():
    contribution = yaml.safe_load((HERE / "contribution.yaml").read_text(encoding="utf-8"))
    harness = pins(contribution)
    repo = harness["dispatch_repo"]
    art = harness.get("artifacts") or {"cases": "m4-frozen-cases", "raw_prefix": "m4-raw-"}
    cases_bytes = (HERE / "freeze-cases.jsonl").read_bytes()
    sha = hashlib.sha256(cases_bytes).hexdigest()
    if harness.get("cases_sha256") and harness["cases_sha256"] != sha:
        raise SystemExit(f"freeze-cases.jsonl sha256 {sha} != contribution harness.cases_sha256 {harness['cases_sha256']}")
    tag = f"freeze/{contribution['id']}"
    tag_commit = subprocess.run(["git", "rev-parse", f"{tag}^{{commit}}"], capture_output=True, text=True)
    if tag_commit.returncode != 0:
        raise SystemExit(f"no local tag {tag}: run `workbench freeze {contribution['id']} --commit` and push the tag")
    freeze_commit = tag_commit.stdout.strip()
    cases_url = (f"https://raw.githubusercontent.com/{harness['cases_repo']}/{freeze_commit}/"
                 + harness["cases_path"].format(id=contribution["id"]))
    runs = Path(os.environ.get("WORKBENCH_RUNS", HERE / "runs"))
    runs.mkdir(parents=True, exist_ok=True)

    run_id = os.environ.get("M4_RUN_ID")
    dispatched_at = None
    if not run_id:
        with urllib.request.urlopen(cases_url, timeout=60) as resp:  # noqa: S310 - https host from contribution.yaml
            public = resp.read()
        if hashlib.sha256(public).hexdigest() != sha:
            raise SystemExit(f"{cases_url} does not match the local frozen cases (push the freeze tag first)")
        dispatched_at = dt.datetime.now(dt.timezone.utc)
        sh("gh", "workflow", "run", harness["workflow"], "-R", repo, "--ref", harness["dispatch_ref"],
           "-f", f"cases_url={cases_url}", "-f", f"cases_sha256={sha}", "-f", f"harness_ref={harness['commit']}",
           "-f", f"engine_commit={harness['engine_commit']}", "-f", f"model={harness['model']}",
           "-f", f"template_id={harness['template_id']}",
           "-f", f"constraints_url={harness['constraints_url']}",
           "-f", f"constraints_sha256={harness['constraints_sha256']}",
           "-f", f"provider_order={harness.get('provider_order', '')}",
           "-f", f"llm_seed={harness.get('llm_seed', '')}",
           "-f", f"max_parallel={harness.get('max_parallel', '6')}",
           *(["-f", f"case_filter={os.environ['M4_CASE_FILTER']}"] if os.environ.get("M4_CASE_FILTER") else []))
        print(f"dispatched {harness['workflow']} on {repo}@{harness['dispatch_ref']} (harness {harness['commit'][:12]}, "
              f"engine {harness['engine_commit'][:12]}) with cases {sha[:12]}", flush=True)
        for _ in range(30):
            time.sleep(10)
            rows = json.loads(sh("gh", "run", "list", "-R", repo, "--workflow", harness["workflow"],
                                 "--branch", harness["dispatch_ref"], "--limit", "5",
                                 "--json", "databaseId,createdAt,status,headSha"))
            rows = [r for r in rows if dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
                    >= dispatched_at - dt.timedelta(seconds=30)]
            if rows:
                run_id = str(rows[0]["databaseId"])
                break
        if not run_id:
            raise SystemExit("dispatched, but no run appeared within five minutes")
    print(f"run {run_id}: https://github.com/{repo}/actions/runs/{run_id}", flush=True)

    while True:
        info = json.loads(sh("gh", "run", "view", run_id, "-R", repo, "--json",
                             "status,conclusion,headSha,createdAt,updatedAt,url"))
        if info["status"] == "completed":
            break
        print(f"  {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} status={info['status']}", flush=True)
        time.sleep(120)
    with tempfile.TemporaryDirectory() as tmp:
        sh("gh", "run", "download", run_id, "-R", repo, "-n", art["cases"], "-D", tmp)
        manifest = json.loads(next(Path(tmp).rglob("run-manifest.json")).read_text(encoding="utf-8"))
    tag_sha = json.loads(sh("gh", "api", f"repos/{repo}/commits/{harness['dispatch_ref']}"))["sha"]
    if info["headSha"] != tag_sha:
        raise SystemExit(f"run {run_id} ran workflow commit {info['headSha']}, dispatch tag {harness['dispatch_ref']} is {tag_sha}")
    for key, want in (("harness_commit", harness["commit"]), ("engine_commit", harness["engine_commit"]),
                      ("cases_sha256", sha), ("cases_url", cases_url), ("model", harness["model"]),
                      ("template_id", harness["template_id"]), ("constraints_url", harness["constraints_url"]),
                      ("constraints_sha256", harness["constraints_sha256"]),
                      ("provider_order", harness.get("provider_order", "")),
                      ("llm_seed", str(harness.get("llm_seed", "")))):
        if manifest.get(key) != want:
            raise SystemExit(f"run {run_id} {key}={manifest.get(key)!r}, contribution names {want!r}")

    with tempfile.TemporaryDirectory() as tmp:
        sh("gh", "run", "download", run_id, "-R", repo, "-p", f"{art['raw_prefix']}*", "-D", tmp)
        files = sorted(Path(tmp).rglob("*.jsonl"))
        if not files:
            raise SystemExit(f"run {run_id} produced no {art['raw_prefix']}* artifacts")
        out = runs / f"run-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{run_id}.jsonl"
        header = {
            "event": "run", "t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id, "run_url": info["url"], "conclusion": info["conclusion"],
            "harness_repo": harness["repo"], "harness_commit": manifest["harness_commit"],
            "engine_commit": manifest["engine_commit"], "dispatch_repo": repo, "dispatch_commit": info["headSha"],
            "model": harness["model"], "template_id": harness["template_id"],
            "constraints_url": harness["constraints_url"], "constraints_sha256": harness["constraints_sha256"],
            "cases_url": cases_url, "cases_sha256": sha,
            "dispatched_at": dispatched_at.isoformat() if dispatched_at else None,
            "case_files": [f.name for f in files],
        }
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            for f in files:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        fh.write(line.rstrip("\n") + "\n")
    print(f"wrote {out} ({out.stat().st_size} bytes; export needs --url above 2,000,000)")


if __name__ == "__main__":
    main()
