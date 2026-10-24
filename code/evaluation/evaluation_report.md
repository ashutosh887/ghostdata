# Evaluation report

All numbers come from `python3 code/evaluation/report.py`, which reruns every scorer below. Labelled data is
the 32 sample cases: 22 for development and 10 frozen as a holdout before any resolver code existed
(`code/evaluation/splits.py`, seed 20261024, stratified by status).

## Metrics

- **False COMPLETE**: cases certified as deleted while data remains. This is the headline: it is the failure
  the brief describes. **Steps on NOT_APPLICABLE**: deletion work proposed without authority.
- **Status**: case-level `deletion_status` accuracy.
- **Step P / R / F1**: steps matched as multisets on (phase, system_id, resource_id, operation, state, evidence_id).
  The second F1 ignores evidence_id, which separates finding the right records from citing the right source.
- **Field accuracy**: each step field compared position by position against the sample answer.
- **Sequence**: whether the shared steps appear in the same order, and 1 minus the normalised edit distance
  between the two step lists.

## Development split (22 samples)

| System | False COMPLETE | Steps on NOT_APPLICABLE | Status | Exact steps_json | Step P / R / F1 | F1 ignoring evidence_id | Order agrees | Sequence similarity |
|---|---|---|---|---|---|---|---|---|
| Agent (model + code) | 0 | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.984 / 0.933 / 0.958 | 0.958 | 22/22 (1.000) | 0.927 |
| Rules only (no model) | 0 | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.984 / 0.933 / 0.958 | 0.958 | 22/22 (1.000) | 0.927 |
| Baseline: trust the workflow's claim | 5 | 0 | 14/22 (0.636) | 0/22 (0.000) | 0.000 / 0.000 / 0.000 | 0.000 | 0/22 (0.000) | 0.0 |
| Baseline: always INCOMPLETE | 0 | 0 | 15/22 (0.682) | 0/22 (0.000) | 0.000 / 0.000 / 0.000 | 0.000 | 0/22 (0.000) | 0.0 |

Field accuracy for the agent: phase 0.948, system_id 0.873, resource_id 0.858, operation 0.873, state 0.873, evidence_id 0.940.

Per class for the agent: COMPLETE precision 7/7 (1.000), recall 7/7 (1.000); INCOMPLETE precision 15/15 (1.000), recall 15/15 (1.000); NOT_APPLICABLE precision 0/0, recall 0/0.

The 8 dev cases that are not exact: case_18 and case_20 each need a security audit record whose id appears nowhere
in the dataset; case_21, case_25, case_26 and case_27 each miss an anonymised analytics record that carries no
identifier and shares its batch with other requests (F-004); case_28 and case_29 have swapped accounts because
no evidence separates their two candidates (D-011).

## Holdout (10 samples, scored once)

Not printed here yet. It is printed by `report.py --holdout` in the final packaging run. The holdout was seen once before that, by accident, while recording cached answers (D-003).

## Custom evaluation cases

Six hand-built cases run through the real pipeline on a copy of the dataset with the case's users, activity and
evidence added (`code/evaluation/custom.py`). Result: 6/6 exact.

| Case | What it tests | Why it matters | Expected |
|---|---|---|---|
| case_901 | Oldest email in the request, middle email's hash in the evidence | Identity must include every historical email and its hash, not just the current one. | INCOMPLETE, 4 steps |
| case_902 | Successful delete undone by an active sync | A reported SUCCESS is a claim; an enabled flow is a recreation risk and must be disabled before deleting its copy. | INCOMPLETE, 7 steps |
| case_903 | Tombstone with leftover PII beside a retained audit record | rule_15 keeps the stable user_id but removes direct identifiers; rule_12 keeps the audit record. | INCOMPLETE, 5 steps |
| case_904 | Spanish access request that refuses deletion | Only a request that authorises deletion gets steps; an access request is NOT_APPLICABLE with []. | NOT_APPLICABLE, 0 steps |
| case_905 | Injected instructions in the request and in the evidence | Text may state facts but cannot change status logic; the restore risk and the exposed message must still be reported. | INCOMPLETE, 7 steps |
| case_906 | Late evidence that would flip a COMPLETE | Only information available at or before audit_at may decide the case. | COMPLETE, 1 step |

Run output:

```
PASS case_901 Oldest email in the request, middle email's hash in the evidence: expected INCOMPLETE, got INCOMPLETE
PASS case_902 Successful delete undone by an active sync: expected INCOMPLETE, got INCOMPLETE
PASS case_903 Tombstone with leftover PII beside a retained audit record: expected INCOMPLETE, got INCOMPLETE
PASS case_904 Spanish access request that refuses deletion: expected NOT_APPLICABLE, got NOT_APPLICABLE
PASS case_905 Injected instructions in the request and in the evidence: expected INCOMPLETE, got INCOMPLETE
PASS case_906 Late evidence that would flip a COMPLETE: expected COMPLETE, got COMPLETE
```

## Intent probes outside the dataset

Hand-written requests in five more languages and phrasings the dataset does not use: synonyms, corrections,
hypotheticals, opt-outs and injected instructions (`code/evaluation/intent_probes.json`). The tuned set found
the two misses fixed in F-005; the held-out set was written after that fix, run once, and never used to change it.

```
tuned: n=23 model 23/23, keywords 12/23
held_out: n=12 model 12/12, keywords 9/12
```

## Ablations

| Arm | Dev false COMPLETE | Dev status | Dev exact | Dev step F1 | Custom exact | Test rows changed | Test new COMPLETE | Validator |
|---|---|---|---|---|---|---|---|---|
| full agent | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 0 | 0 | passed |
| no model: keyword intent, no document reading | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 5 | 4 | FAILED |
| no identity history: current email, phone and hash only | 2 | 20/22 (0.909) | 12/22 (0.545) | 0.897 | 5/6 | 71 | 49 | passed |
| no time cut: evidence after audit_at counts | 0 | 21/22 (0.955) | 14/22 (0.636) | 0.913 | 5/6 | 15 | 0 | passed |
| no request-time bound on discovery | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.951 | 6/6 | 2 | 0 | passed |
| replica tables ignored | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.950 | 6/6 | 11 | 2 | passed |
| document readings swapped between screenshots | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 7 | 6 | FAILED |

Each removed mechanism changes answers; the interpretation is in `code/docs/DECISIONS.md` (D-012).

## Failures found and improvements made

Full entries, each with cause, fix and before-and-after numbers, are in `code/docs/FAILURES.md`.

- F-001. Citations pointed at evidence captured after audit_at
- F-002. Keyword intent missed "I'm deleting my account"
- F-003. Unknown state passed as compliant
- F-004. A queue-order rule that the data does not support
- F-005. Corrections and hypotheticals read as deletion
- F-006. The evaluation report said "not run" for the custom cases
- F-007. One unknown email stopped the whole run
- F-008. Most investigations ran out of rounds
- F-009. A same-time tie could keep the state and drop its proof

## Score history on the development split

| When (UTC) | Label | System | Split | Cases | False COMPLETE | Status | Exact | Step F1 | F1 no evidence | Order ok |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-24 14:34 | baseline: trust the workflow claim | trust_workflow | dev | 22 | 5 | 14/22 (0.636) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:34 | baseline: always INCOMPLETE | always_incomplete | dev | 22 | 0 | 15/22 (0.682) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:34 | placeholder: all NOT_APPLICABLE | resolver | dev | 22 | 0 | 0/22 (0.000) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:42 | resolver v1: rules intent, identity links, state at audit_at | resolver | dev | 22 | 0 | 20/22 (0.909) | 9/22 (0.409) | 0.748 | 0.929 | 22/22 (1.000) |
| 2026-10-24 14:43 | v2: proofs since last change; -ing deletion verbs | resolver | dev | 22 | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.954 | 0.954 | 22/22 (1.000) |
| 2026-10-24 14:44 | v3: anonymised analytics by worker queue order when counts match | resolver | dev | 22 | 0 | 22/22 (1.000) | 15/22 (0.682) | 0.966 | 0.966 | 22/22 (1.000) |
| 2026-10-24 14:50 | v4 agent: model intent + document reading | agent | dev | 22 | 0 | 22/22 (1.000) | 15/22 (0.682) | 0.966 | 0.966 | 22/22 (1.000) |
| 2026-10-24 14:52 | v5: drop queue-order guess for multi-case batches | agent | dev | 22 | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 0.958 | 22/22 (1.000) |
| 2026-10-24 14:56 | v6: investigator on flagged cases (0 accepted) | agent | dev | 22 | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 0.958 | 22/22 (1.000) |
