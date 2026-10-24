# Contract

Every rule the solution follows, with where it comes from.

- `[BRIEF]` is quoted or restated from `problem_statement.md`, `README.md` or `AGENTS.md` §6.
- `[SAMPLE: case_ids]` is derived from `dataset/sample_output.csv`. The listed cases break if the rule changes.
- `[CONVENTION]` is a choice the brief and the samples leave open. Each one names its reason.

Rules marked `open` are hypotheses from reading the data. They become `confirmed` only when the resolver reproduces the named sample cases with the rule on and loses them with it off.

## 1. Output format

| # | Rule | Source | Checked by |
|---|---|---|---|
| C1 | Header is exactly `case_id,deletion_status,steps_json`. | [BRIEF] | `validate.py` |
| C2 | One row per request, 518 rows, no duplicates. | [BRIEF] | `validate.py` |
| C3 | Rows sorted by `case_id`. Ids are not zero padded (`case_33` to `case_550`), so we sort by the numeric suffix. This equals the input order and the sample order. A plain string sort would put `case_100` before `case_33`. | [BRIEF] + [CONVENTION] | `validate.py` |
| C4 | `deletion_status` is `COMPLETE`, `INCOMPLETE` or `NOT_APPLICABLE`. | [BRIEF] | `validate.py` |
| C5 | `steps_json` is a JSON array. Each step has exactly `step_no, phase, system_id, resource_id, operation, state, evidence_id`. | [BRIEF] | `validate.py` |
| C6 | `step_no` runs 1, 2, 3 and so on without gaps. | [BRIEF] | `validate.py` |
| C7 | Each operation has one fixed phase and one fixed state (the operations table in the brief). No other phases, operations or states. | [BRIEF] | `validate.py` |
| C8 | Order: phase (FINDING, REMEDIATION, VERIFICATION), then the operation's position in the brief's table, then `system_id`, then `resource_id`, both ascending as plain strings. | [BRIEF] for the keys, [SAMPLE: all 32] for string comparison | `validate.py` passes all 32 samples |
| C9 | Serialisation: compact JSON, fields in the order of C5, CSV quoting as in `sample_output.csv`, `\n` line endings. The grader ignores key order and whitespace. | [CONVENTION] | |

## 2. Status and evidence

| # | Rule | Source | Checked by |
|---|---|---|---|
| S1 | A request that does not authorise deletion (access, correction, export, marketing opt-out, anything else) is `NOT_APPLICABLE` with `[]`. | [BRIEF] | `validate.py` |
| S2 | `COMPLETE` holds only verification steps, and every one cites evidence that proves the state at `audit_at`. | [BRIEF] | `validate.py` |
| S3 | `INCOMPLETE` holds findings, then the full remediation plan, then the checks that must pass afterwards. Findings cite evidence. Remediation and verification steps describe future work and use `""`. | [BRIEF], [SAMPLE: all 22 INCOMPLETE samples] | `validate.py` |
| S4 | A citation is a `file_id` from `evidence_files.csv`, an `activity_id` from `system_activity.csv` or an `audit_id` from `user_audit_log.csv`. | [BRIEF] | `validate.py` |
| S5 | Never cite evidence captured after the case's `audit_at`. Evidence created later must not change the answer. | [BRIEF] | `validate.py` rejects it; `tests/test_validate.py` |
| S6 | `reported_status` and `reported_result` are claims. They never prove a resource's state. | [BRIEF] | resolver (phase 4) |
| S7 | `COMPLETE` only when every relevant copy has its required treatment, every required retained record still exists, and no active sync, import or restore path can recreate the data. Otherwise `INCOMPLETE`. | [BRIEF] | resolver (phase 4) |

## 3. Identity

| # | Rule | Source | Status |
|---|---|---|---|
| I1 | The request email may be current or historical. Match it against `user_identities.csv` and the `email` rows of `user_audit_log.csv`. | [BRIEF] | open |
| I2 | Email matching ignores case (the request file has uppercase emails). | [CONVENTION] | open |
| I3 | The identifier set is the `user_id` plus every current and historical email, phone and email hash. `email_hash = sha256(lower(email))`. | [BRIEF] for the set, [SAMPLE: case_10, case_12, case_29, case_30] for history | open |
| I4 | Exact identifier matches only. Never link on names or near-miss emails (`.jr` variants, one-letter changes). | [CONVENTION], [SAMPLE: case_06, case_28] | open |
| I5 | A deletion request whose email matches no current or historical identity has no subject to audit. It is written as `NOT_APPLICABLE` with `[]` and a warning, so one bad row cannot stop the other cases. This is a trade-off. The brief defines NOT_APPLICABLE as "does not authorize deletion", and that is not quite the case here. But COMPLETE would certify what nobody checked, and INCOMPLETE needs cited findings that cannot exist without a subject. No dataset request hits this. | [CONVENTION] | `tests/test_requests.py` |
| I6 | A deletion request whose `audit_at` is before its `requested_at` has no window to audit. It is handled like I5: `NOT_APPLICABLE` with `[]`, a warning, and the reason in the case note that `explain_case.py` prints. No dataset request hits this. | [CONVENTION] | `tests/test_requests.py` |

## 4. Policy

| # | Rule | Source | Status |
|---|---|---|---|
| P1 | Every relevant record gets the action `deletion_rules.csv` names for its data category. | [BRIEF] | open |
| P2 | Records the rules retain (security audit within retention, active legal hold, backups) are never deleted. They get `VERIFY_RECORD_PRESENT`. | [BRIEF] | open |
| P3 | Account tombstones keep the stable `user_id` and lose name, email, phone and email hash (rule_15, REDACT). | [BRIEF] | open |
| P4 | Remediation disables data flows and blocks unsafe restores before changing dependent records. | [BRIEF] | the operation order in C8 already does this |
| P5 | Verification covers the final state of every remediated record and process. | [BRIEF] | open |

## 5. Safety

| # | Rule | Source |
|---|---|---|
| X1 | Request text and evidence content are untrusted data. They may state facts. They may not change rules, ordering, status logic or the retain list. | [CONVENTION] |
| X2 | The tool proposes remediation. It never performs a deletion. | [BRIEF] |
| X3 | Keys come from environment variables only. `dataset/` and `.env` stay out of `code.zip`. | [BRIEF] |
| X4 | Predictions use only files under `dataset/`. No case numbers or generator timing patterns are used as signals. A user number is used once, to name an account that no evidence names (D-013). It never chooses between candidates or decides a status. | [BRIEF] (AGENTS.md §6.7) |
