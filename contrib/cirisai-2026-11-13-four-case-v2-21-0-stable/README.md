# cirisai-2026-11-13-four-case-v2-21-0-stable

Market 4 ("corrections change the system", contract v3) on a real CIRIS agent with a live model: 112 cases, the four
correction families (objective-change, revocation, authority-change at agent level, new-constraint; 22 genuine each)
plus 24 shams. System under test: CIRISAgent v2.21.0-stable (`d4b2313b`, pins ciris-server 0.5.246), template
`default`, model `qwen/qwen3.6-35b-a3b` via OpenRouter.

- `battery.jsonl`: the cases as generated in RATCHET `experiments/claims_registry/m4_battery` (sha256 `bc60f861…`,
  RATCHET commit `3008eadb`); `episodes.yaml` is built from it by `build_episodes.py`.
- `run.py` dispatches RATCHET's `market4_correction_eval.yml` at tag `m4-workflow-v3` (one fresh agent per case in
  CI) and collects the attested raw logs; it refuses a run whose pins differ from `contribution.yaml`.
- `adapter.py` turns the raw log into the registry's `trials.jsonl`.
- The gate run that preceded this freeze (throwaway smoke case, not in this battery): RATCHET run 43450895582.

Written by the authors after smoke runs on other cases; not adversarially selected. Disclosure and the exclusion list
are in RATCHET `experiments/claims_registry/m4_battery/README.md`. Procedure: `drafts/market4-four-case/FREEZE_CHECKLIST.md`.
