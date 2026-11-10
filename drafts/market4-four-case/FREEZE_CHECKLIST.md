# Market 4 four-case contribution: draft → exported sketch

This draft is **not frozen**. Do not start this checklist until a CIRISAgent release exists that pins ciris-server
≥ 0.5.246, the fix for CIRISServer#871. On v2.20.0-stable the node refuses every WA-approved amendment
(`response_signer_not_a_seated_wa`). Run every command from the path it names. Names in `<…>` are filled as you go:
- `<REL>` is the release tag and `<E>` its full commit;
- `<H>` is the harness commit;
- `<ID>` is the contribution id.

## 0. Preconditions (RATCHET and CIRISAgent)

1. **Harness branch on the release.** The harness files are `tools/qa_runner/modules/correction_episode_tests.py`,
   its registration in `config.py` / `runner.py` / `__main__.py` / `_module_metadata.py`, and
   `tests/tools/qa_runner/test_correction_episode_pure.py`.
   - Base: `git worktree add <wt> <REL>`, then `git switch -c market4/on-<REL>`.
   - Cherry-pick the harness commits of `market4/on-v2200` in order, from `v2.20.0-stable..market4/on-v2200`.
   - Check `git diff --quiet <E> HEAD -- ciris_engine ciris_adapters main.py requirements.txt && echo IDENTICAL`.
   - Run `python -m pytest -c /dev/null --rootdir . tests/tools/qa_runner/test_correction_episode_pure.py -q --noconftest`.
   - Push `market4/on-<REL>`. `<H>` is its tip.
2. **One gate run with the smoke cases, not the battery.** In RATCHET:
   - `gh workflow run market4_correction_eval.yml --repo CIRISAI/RATCHET -f cases_url=<smoke-cases-v6 raw URL> -f cases_sha256=<sha> -f case_filter=smoke6-obj -f harness_ref=<H> -f engine_commit=<E>`
   - Pass condition: the raw log shows `amendment_outcome: landed`, `occurrences_readback` shows `agent_agreed: true`,
     and `ceg_rows` checks hold.
   - If the amendment is still refused, stop here.
3. **Constraints.** Copy that job's attested `pip-freeze.txt` to
   `experiments/claims_registry/m4_env/constraints-cirisagent-<REL>-<E:8>.txt`, update that directory's README,
   commit and push. Record the raw URL at that commit and the file's sha256.
4. **Workflow.** Set the defaults `harness_ref=<H>` and `engine_commit=<E>` in
   `.github/workflows/market4_correction_eval.yml`, commit, then
   `git tag m4-workflow-v3 && git push origin master m4-workflow-v3`.
5. **Battery.** In `experiments/claims_registry/m4_battery`:
   - `python3 -I build_battery.py --system CIRISAgent --version <REL> --engine-commit <E> --model qwen/qwen3.6-35b-a3b --out battery-draft.jsonl`
   - `python3 validate_battery.py battery-draft.jsonl <wt>/tools/qa_runner/modules/correction_episode_tests.py`. It must
     print "all rules hold".
   - Commit and push. Record the file's sha256 `<B>`.

## 1. Contribution (workbench fork, branch `market4-ciris`)

```
cd ai-safety-claims-workbench && git switch market4-ciris && git pull
workbench new --market market-04 --submitter cirisai --type custom --slug four-case-<REL with dots as dashes>   # ids are [a-z0-9-]; prints contrib/<ID>
cp drafts/market4-four-case/{run.py,adapter.py,build_episodes.py,contribution.yaml} contrib/<ID>/
mkdir -p contrib/<ID>/tests && cp drafts/market4-four-case/tests/test_adapter.py contrib/<ID>/tests/
cp <RATCHET>/experiments/claims_registry/m4_battery/battery-draft.jsonl contrib/<ID>/battery.jsonl
(cd contrib/<ID> && python build_episodes.py battery.jsonl <B>)                   # writes episodes.yaml
```

1. Edit `contrib/<ID>/contribution.yaml` and replace every `<<FILL: …>>`:
   - `id`, `system.version`;
   - `harness.branch` / `commit` / `engine_commit` / `dispatch_ref` (`m4-workflow-v3`) / `constraints_url` / `constraints_sha256`.

   Leave `harness.cases_sha256` empty.
2. **Authority bound (CC 2.6.7).** If any case unseats an authority, set `response_bound_hours: 72` and say so in
   the description.
   - In this battery no case removes a WA seat. Authority-change cases narrow whose requests the agent honours, so
     the field stays `null`.
   - Re-check this if the battery changes.
3. `python -m pytest contrib/<ID>/tests -q`, then commit the contribution: `git add contrib/<ID> && git commit`.

## 2. Freeze and publish

```
workbench freeze <ID> --commit             # writes freeze.yaml + freeze-cases.jsonl, commits "Freeze <ID>", tags freeze/<ID>
git push origin market4-ciris freeze/<ID>
```

The raw URL at the tag must now serve `freeze-cases.jsonl`, and `run.py` checks it.

## 3. Run (or adopt a run)

```
cd contrib/<ID> && WORKBENCH_RUNS=runs python run.py      # dispatches at m4-workflow-v3 and waits
# or adopt a finished run of exactly these pins:
M4_RUN_ID=<run id> python run.py
```

`run.py` refuses a run whose manifest names a different harness, engine, cases, constraints, provider order or seed,
or one that ran a different workflow commit. Expect about 112 jobs at roughly 11–22 minutes each (smoke measurement)
with `max_parallel` 6.

## 4. Export the sketch

```
workbench export <ID> --log contrib/<ID>/runs/run-<…>.jsonl --url <public URL of that raw log>
```

- `--url` is required when the raw log is over 2,000,000 bytes, and it will be at this size.
- Publish the log first, for example as a release asset or in a workbench `runs/` commit, and use its stable raw URL.
- The adapter fails if a case has more than one verdict. A repeats run must become a separate contribution.

## 5. Hand edits, then dry run

In the registry checkout (`$WORKBENCH_REGISTRY`, default `../ai-safety-claims`), add the three fields the export does
not write to `sketches/<ID>/attempt.yaml`:
- `contact:`, a maintainer-reachable address;
- `publishedAt:`, the ISO time the evidence became public;
- `artifact:`, the URL of the frozen contribution at `freeze/<ID>`.

Then:

```
cd $WORKBENCH_REGISTRY && python -m validator dry-run sketches/<ID>
```

Read the gap list. The site's "Completeness" percentage is a machine score that this validator's
`_line_check_id` currently caps: exercised bars are listed as `exercised:<bar>` but matched as `<bar>`. It is not a
maintainer rating.
