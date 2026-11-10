"""Adapter: this contribution's JSON-lines raw log -> the registry's trials.jsonl.

Usage: python adapter.py <raw log> <freeze-cases.jsonl> <trials.jsonl>

One trial per frozen case that reached a `verdict` event. It FAILS (exit non-zero, nothing written) when:
- a case has more than one verdict, more than one start, or a verdict without a start (one trial per case; a
  repeated run of one case must be exported as its own contribution, never silently reduced to its last verdict);
- the raw log names a case that is not frozen;
- a case's start event records a case_hash different from the frozen one;
- a verdict lacks a result field its kind needs.
It copies the verdict's result fields, the frozen case hash, started_at/finished_at from the case's own start/end
events, and every other verdict field (amendment_outcome, auditor fields, tags, answers, statuses) into `output`.
It decides nothing. Cases that ended in a harness error produce no trial; the dry run then lists them as missing.
"""

import json
import sys
from pathlib import Path

import yaml

RESULT_KEYS = {"genuine": ("uptake", "persisted_after_reset"), "sham": ("sham_succeeded",)}


class AdapterError(SystemExit):
    pass


def load_cases(path):
    cases = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            cases[c["case_id"]] = c
    return cases


def read_raw(raw):
    header, events = {}, {}
    with open(raw, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event") == "run" and not row.get("case_id"):
                header = row
                continue
            if not row.get("case_id"):
                raise AdapterError(f"line {n}: event {row.get('event')!r} names no case")
            events.setdefault(row["case_id"], []).append((n, row))
    return header, events


def trials(raw, cases, contribution):
    header, events = read_raw(raw)
    records = []
    for cid, rows in events.items():
        if cid not in cases:
            raise AdapterError(f"raw log names case {cid}, which is not frozen")
        by = {}
        for n, row in rows:
            by.setdefault(row["event"], []).append((n, row))
        if "verdict" not in by:
            continue
        if len(by["verdict"]) > 1:
            raise AdapterError(f"case {cid} has {len(by['verdict'])} verdicts (raw lines "
                               f"{[n for n, _ in by['verdict']]}); one trial per case: export each repeat separately")
        starts = by.get("start", [])
        if len(starts) != 1:
            raise AdapterError(f"case {cid} has {len(starts)} start events; expected exactly one")
        start = starts[0][1]
        frozen_hash = cases[cid].get("case_hash")
        logged_hash = start.get("case_hash_field")
        if frozen_hash and logged_hash and logged_hash != frozen_hash:
            raise AdapterError(f"case {cid}: the run started from case_hash {logged_hash}, frozen is {frozen_hash}")
        verdict = by["verdict"][0][1]
        kind = cases[cid]["kind"]
        missing = [k for k in RESULT_KEYS[kind] if k not in (verdict.get("result") or {})]
        if missing:
            raise AdapterError(f"case {cid}: verdict lacks {missing}")
        result = {k: bool(verdict["result"][k]) for k in RESULT_KEYS[kind]}
        system = (by.get("system") or [(0, {})])[0][1]
        output = {k: v for k, v in verdict.items() if k not in ("t", "case_id", "event", "result")}
        output["system_record"] = {k: system.get(k) for k in ("ciris_version_constant", "engine_commit",
                                                                "harness_commit", "github_run_url", "model", "template")}
        output["case_line_sha256"] = start.get("case_line_sha256")
        ends = by.get("end") or []
        records.append({
            "trial_id": f"t-{cid}", "case_id": cid, "case_hash": frozen_hash,
            "system": {"name": contribution["system"]["name"], "version": str(contribution["system"]["version"])},
            "started_at": start["t"], "finished_at": ends[-1][1]["t"] if ends else verdict["t"],
            "scorer": {"name": contribution["scorer"]["name"], "version": str(contribution["scorer"]["version"])},
            "input": {"correction": cases[cid]["correction"], "probe": cases[cid]["probe"],
                      "pressure": cases[cid].get("pressure")},
            "output": output,
            "result": result,
            "harness": {"run_url": header.get("run_url"), "harness_commit": header.get("harness_commit"),
                        "engine_commit": header.get("engine_commit"), "model": header.get("model"),
                        "conclusion": header.get("conclusion")},
            "raw_ref": f"{Path(raw).name} lines {rows[0][0]}-{rows[-1][0]}",
        })
    records.sort(key=lambda r: r["case_id"])
    return records, len(events)


def main(raw, cases_path, out):
    contribution = yaml.safe_load((Path(__file__).parent / "contribution.yaml").read_text(encoding="utf-8"))
    records, n_cases = trials(raw, load_cases(cases_path), contribution)
    Path(out).write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records),
                         encoding="utf-8")
    print(f"{len(records)} trials from {n_cases} cases in the raw log")


if __name__ == "__main__":
    main(*sys.argv[1:4])
