"""Adapter: this contribution's JSON-lines raw log -> the registry's trials.jsonl.

Usage: python adapter.py <raw log> <freeze-cases.jsonl> <trials.jsonl>
One trial per case that reached a `verdict` event. It copies the verdict's result fields, the frozen
case hash, timestamps from the case's start/end events, and the harness facts (deferral seen, identity
changed, HTTP statuses, answers) into `output`. It decides nothing. Cases that ended in a harness error
produce no trial; the dry run then lists them as missing.
"""

import json
import sys
from pathlib import Path

import yaml

RESULT_KEYS = {"genuine": ("uptake", "persisted_after_reset"), "sham": ("sham_succeeded",)}


def main(raw, cases_path, out):
    contribution = yaml.safe_load((Path(__file__).parent / "contribution.yaml").read_text(encoding="utf-8"))
    cases = {c["case_id"]: c for c in map(json.loads, Path(cases_path).read_text(encoding="utf-8").splitlines()) if c}
    header, events = {}, {}
    with open(raw, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "run" and not row.get("case_id"):
                header = row
                continue
            events.setdefault(row["case_id"], []).append((n, row))
    records = []
    for cid, rows in events.items():
        if cid not in cases:
            raise SystemExit(f"raw log names case {cid}, which is not frozen")
        by = {}
        for _, row in rows:
            by.setdefault(row["event"], []).append(row)
        if "verdict" not in by:
            continue
        verdict = by["verdict"][-1]
        kind = cases[cid]["kind"]
        result = {k: bool(verdict["result"][k]) for k in RESULT_KEYS[kind]}
        system = by.get("system", [{}])[0]
        output = {k: v for k, v in verdict.items() if k not in ("t", "case_id", "event", "result")}
        output["system_record"] = {k: system.get(k) for k in ("ciris_version_constant", "engine_commit", "harness_commit", "github_run_url", "model", "template")}
        records.append({
            "trial_id": f"t-{cid}", "case_id": cid, "case_hash": cases[cid]["case_hash"],
            "system": {"name": contribution["system"]["name"], "version": str(contribution["system"]["version"])},
            "started_at": by["start"][0]["t"], "finished_at": by["end"][-1]["t"],
            "scorer": {"name": contribution["scorer"]["name"], "version": str(contribution["scorer"]["version"])},
            "input": {"correction": cases[cid]["correction"], "probe": cases[cid]["probe"], "pressure": cases[cid].get("pressure")},
            "output": output,
            "result": result,
            "harness": {"run_url": header.get("run_url"), "harness_commit": header.get("harness_commit"),
                        "engine_commit": header.get("engine_commit"), "model": header.get("model"),
                        "conclusion": header.get("conclusion")},
            "raw_ref": f"{Path(raw).name} lines {rows[0][0]}-{rows[-1][0]}",
        })
    records.sort(key=lambda r: r["case_id"])
    Path(out).write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    print(f"{len(records)} trials from {len(events)} cases in the raw log")


if __name__ == "__main__":
    main(*sys.argv[1:4])
