"""Write episodes.yaml from the RATCHET battery (experiments/claims_registry/m4_battery/battery-draft.jsonl).

    python build_episodes.py <battery.jsonl> [<expected sha256>]

Deterministic. Copies each battery case into the workbench Market 4 episode shape. The builder (src/workbench/
markets/market_04) then keeps setup, channel, correction, probe, target, check, source, examinee_model, the genuine
fields and sham_type verbatim, and sets unit_id to "<system name> <version>"; the battery's grid row survives in
check.tags (unit / attacks_unit). Every delivery vector is declared with an empty prefix, so the correction text is
exactly the battery's.
"""

import hashlib
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
VECTORS = ("wa-interact", "observer-interact", "forged-jwt", "observer-resolve", "observer-memory-store",
           "attack-then-genuine", "observer-self-promote", "observer-reroute", "wa-then-impersonate")
GENUINE_FIELDS = ("correction_family", "enforceable_by_tool_removal", "verbal_agreement_probe")


def episodes_from(lines):
    eps = []
    for line in lines:
        if not line.strip():
            continue
        c = json.loads(line)
        if c["channel"] not in VECTORS:
            raise SystemExit(f"{c['case_id']}: channel {c['channel']} is not declared")
        ep = {"id": c["case_id"], "kind": c["kind"], "channel": c["channel"], "setup": c["setup"],
              "correction": c["correction"], "probe": c["probe"], "target": c["target"], "check": c["check"],
              "source": c["source"], "examinee_model": c["examinee_model"]}
        if c["kind"] == "genuine":
            ep.update({f: c[f] for f in GENUINE_FIELDS})
        else:
            ep["sham_type"] = c["sham_type"]
        if c.get("pressure"):
            ep["pressure"] = c["pressure"]
        eps.append(ep)
    return eps


def main(battery, expected_sha=None):
    data = Path(battery).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if expected_sha and sha != expected_sha:
        raise SystemExit(f"{battery} sha256 {sha} != expected {expected_sha}")
    eps = episodes_from(data.decode("utf-8").splitlines())
    spec = {"channels": {v: "" for v in VECTORS}, "episodes": eps}
    (HERE / "episodes.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=110),
                                        encoding="utf-8")
    print(f"wrote {len(eps)} episodes from {battery} (sha256 {sha})")


if __name__ == "__main__":
    main(*sys.argv[1:3])
