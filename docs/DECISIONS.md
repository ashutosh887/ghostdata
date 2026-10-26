# Decisions

Each entry: the choice, the alternatives, and the number or reason that chose it.

## D-001. Python standard library only

Python 3.9 or later, no third-party packages. SQL snapshots load with the built-in `sqlite3`. PDFs and screenshots use the `pdftotext` and `tesseract` command-line tools, and model calls go over HTTPS with `urllib`. Rejected: pandas and an SDK per provider. Anyone can run the solution with no install step, and nothing in the data needs more.

## D-002. Rows sorted by the numeric case suffix

The problem statement says to sort by `case_id`. The ids are not zero padded, so a string sort puts `case_100` before `case_33`. Numeric order matches the request file and the sample file. Anything that joins on `case_id` gets the same result from either order; numeric order is the one a reader expects.

## D-003. A frozen holdout of 10 sample cases

`evaluation/splits.py` draws 3 of the 10 COMPLETE and 7 of the 22 INCOMPLETE samples with seed 20261024, before any resolver code existed. Tuning uses the other 22 (dev). The holdout is scored once, after the last change, and that is the number quoted as the result. The scorer refuses to run if the frozen list stops matching its seeded draw. One caveat: my notes on the data were written after reading all 32 answers, so the holdout is held out from tuning, not from my eyes.

Shortly before 02:01 IST on 25 Oct, after the F-008 prompt change, I ran the scorer with `--split all` to record the cached answers for every sample, and it printed one combined line for all 32: 0 false COMPLETE, status 32/32, exact 22/32. With dev at 14/22, that puts the holdout at 10/10 status and 8/10 exact. That was its first look, and it was unplanned. Since then no change has altered any answer on the 550 requests: later commits only handle malformed input (F-007), tooling and documents. The final `report.py --holdout` run is therefore its second look, and it reports the same numbers unless the fresh model run changes an answer.

## D-004. The headline metric is false COMPLETEs, then accuracy

A false COMPLETE certifies a ghost as gone. That is the failure the problem statement is about, and the expensive one. Steps emitted for a NOT_APPLICABLE request (deletion work nobody authorised) come second. Accuracy comes after both. On dev, trusting the workflow's own claim gets 14/22 statuses right and certifies 5 ghosts. Always answering INCOMPLETE gets 15/22 and certifies none, but gets every real COMPLETE wrong. The resolver has to beat both on both counts.

## D-005. Activity rows are claims, kept apart from observations

`system_activity.csv` is loaded as `Claim` objects, never as observations of state. The problem statement says workflow results are claims, and the samples prove it: support_002 is reported deleted on 2 Sep, yet the support replica still returns it on 7 Sep with no deletion marker. A claim can say that an event happened (a sync ran, a restore ran, a flow check found a connector enabled). It cannot overrule a read-back. The one exception is the 12 `LINK_RESOURCE_IDENTITY` rows, which are catalog facts that tie a screenshot or PDF resource to a user. They become identity links, not state.

## D-006. A lookup counts only when the service that ran it owns the resource

The af_south export has 300 `profile_service` lookups of five-digit `account_*` ids, each carrying a real user's current email. No other file mentions those ids, and `profile_service` is not the account system. Accepting them would link 300 users to accounts that exist nowhere else. The reader drops any log observation whose reporting service is not the owner of the resource's id prefix (lookup lines that name their `system=` explicitly are judged by that field). 300 lines dropped, 770 kept.

## D-007. Absence by omission is limited to what a capture covered

Inventory exports list their systems in `snapshot_scope`. Bundles hold one store per inner snapshot. A replica dump covers the systems that appear in its tables. A record missing from a capture is evidence of absence only for those systems. `customer_data_inventory_20260905.sql` covers `account_service` alone, so it says nothing about a user's search or support records.

## D-008. Intent model: qwen3-235b over qwen3-32b

Both models read all 398 distinct request texts (the 518 test requests plus the 32 samples) with the same prompt and schema. Both found the same 10 non-deletion requests (case_533 to case_542) and agreed with the keyword rules everywhere. qwen3-32b quoted words that are not in the text once, so code fell back to the rules; qwen3-235b grounded all 398. Cost: $0.056 for 235b against $0.039 for 32b. The difference is under two cents, so I took the model that never needed the fallback. Code accepts the model's verdict only when its `quoted_span` is really in the request, which is how a hallucinated or injected answer gets caught.

## D-009. Documents are read by a vision model; a contradicted catalog link is dropped

Tesseract garbles the screenshots (`areedi433@gmail.com` for `areed1433@gmail.com`) and cannot read state, such as whether a connector is healthy or a restore is blocked. qwen3-vl read all 12 linked documents correctly against a hand check ($0.017). The model reports what the page shows; code turns that into present, exposed and active.

`marketing_001` is linked to user_09 (Kwame Mensah) by catalog row activity_4008, but the screenshot shows Soo-jin Park with her own email and phone. The catalog row is an activity, so it is a claim, and the screenshot is evidence that contradicts it. Deleting a record the evidence ties to another person would destroy that person's data. Code drops a link when the linked document shows identifiers and none of them belong to the subject. Alternative considered: the record was recreated with another person's data after the deletion, so it should be reported. That reading flips case_63 from COMPLETE to INCOMPLETE. One case rides on this, and the safer error is not deleting someone else's record.

## D-010. Arm A (rules only) against arm B (rules plus model)

On the 22 dev samples both arms score the same (15/22 exact, step F1 0.966), because no sample has a screenshot and no sample text defeats the patched keywords. On the 518 test cases they differ in 5 cases. Arm A certifies case_39, case_50, case_53 and case_55 as COMPLETE; arm B reads the screens (connector Healthy, analytics profile showing the user's name and email, export Ready, backup restorable) and reports them INCOMPLETE. Arm A's output also fails the validator, with 2 uncited COMPLETE checks. Arm B drops the contradicted marketing link in case_63 (D-009). The model ships where it changed an answer: intent and documents.

## D-011. Account ties are broken by a fixed order, and labelled as ties

Each deletion case owns one account. 249 cases find it through an identity link. 167 more get it by elimination: exactly one in-window account delete by the worker, with a result matching the reported status, is still free. In 109 cases two or more candidates remain and no evidence separates them (case_28 and case_29 on dev are one such pair). Request time predicts the right account in 27 of 54 known pairs, so it carries no signal. The resolver breaks these ties by request time and then case id, only to stay deterministic, and records "tie" as the reason so `explain_case.py` shows it and the investigator gets the case. The alternative, a recurring seconds offset between worker operations, does separate them, but it is a quirk of how the dataset was produced rather than a property of a deletion system, and AGENTS.md §6.7 rules out shortcuts of that kind.

## D-012. What each mechanism is worth (ablations)

`evaluation/ablations.py` switches off one mechanism at a time and reruns the dev samples, the 6 custom cases and all 518 test cases (table in `evaluation/ablations.md`). Ranked by the ghosts each one stops:

- **Historical identifiers** matter most. With current identifiers only, dev certifies 2 ghosts (false COMPLETE), exact match drops 14 to 12, custom case_901 fails, and 49 test cases flip to COMPLETE that the full agent reports as INCOMPLETE.
- **The audit_at cut**: dev status drops to 21/22, custom case_906 fails (late evidence flips it), and 15 test rows change.
- **Document reading**: with the readings swapped between screenshots, 6 test cases flip to COMPLETE and the validator rejects the file. With no model at all, 4 flip. The model reads the screens, and the answers depend on what it reads.
- **Replica tables**: ignoring them loses one dev case (a ghost row in a read replica) and adds 2 false COMPLETEs on the test set.
- **The request-time lower bound** on discovery: one dev case gains a record from an earlier, separate request; 2 test rows change.

Every mechanism that ships changes at least one answer when removed.

## D-013. An account no evidence names takes the user's number

In 15 of 550 deletion cases no identity link and no worker delete point to any account. The resolver then names the account `account_<user number>` (`user_09` gives `account_009`) and checks its absence against the latest full `account_service` capture before `audit_at`. The participant samples use this naming for every such user (case_01 to case_08 and case_10). Two independent reviews flagged it as a numbering shortcut, so I measured removal: dev exact 14 to 12 of 22, 12 test rows lose their account step, no status changes, and case_63 becomes a COMPLETE with no step at all, which breaks S2 because nothing is left to verify. I kept it. It is a naming convention the participant answers show, not a signal hidden in the data, and it never decides a status or picks between real candidates. The seconds-offset tie-breaker (D-011) would do exactly that, so it stays out.

## D-014. Scope uses the time inside a file; citations prefer files captured by audit_at

Some evidence files are captured after `audit_at` but hold a snapshot stamped at or before it (case_525: `evidence_49` captured 31 Jan holds a snapshot dated 29 Jan 12:00, the audit time). Discovery and state use the inner time, because that is when the state was observed. Citations prefer a proof whose file existed by `audit_at` (F-001) and the validator rejects any later file (S5). Filtering scope by capture time as well drops dev exact from 14 to 11 of 22: the sample answers keep the retained records these snapshots show. In the test set it would remove 121 `VERIFY_RECORD_PRESENT` steps and change no status.

## D-015. The deletion worker's action stands only where the category was a system default

When a record's category comes from its system's default rather than from a record type or an attachment signal, the newest deletion-worker action on that system decides the treatment (`policy.py`). A category with an explicit rule, and any RETAIN, always follow `deletion_rules.csv`. The claim chooses which treatment applies. It never proves the resulting state. Removing it drops dev exact from 14 to 12 of 22. It turns 7 test support records from REDACT into DELETE_RECORD, and no status changes.

## D-016. The investigator can confirm and label, but on this data it adds nothing

On the 518 test cases the investigator ran on 121 flagged cases (106 account ties, 12 accounts no evidence names, 5 unverified records, 1 contradicted link). Before F-008 it declared 64 unresolvable, hit the round limit on 57, and made 3 proposals, which code rejected because the records were already in scope. With the stop rule it declared 119 of 121 unresolvable and proposed nothing; on the final live run it declared 117, hit the round limit on 4 and made 2 proposals, which code rejected. This is by construction: code accepts a proposal only when a cited source shows one of the subject's identifiers on the record between the request and the audit, which is the same rule discovery already applies exhaustively. I kept that rule rather than widen it, because a wider rule (a similar name, a near-miss email, a timing pattern) is how a false link gets in. So on this dataset the loop is an independent re-check that found no record the deterministic discovery missed, plus a label for the cases a human should look at. It costs about $0.11 a run. It would earn its place on data where identifiers appear in forms the parsers do not read, such as free text in a support message, and that is where it would be extended.

## D-017. A quoted "yes" is not checked for negation

Code accepts the intent model's verdict only when the quoted words appear in the request. A wrong "yes" that quotes "delete" out of "I do not want to delete my account" would pass that check. I did not add a negation check. A word list for negation in every request language would misread real requests such as "don't keep anything, delete it", and the probes show no such error: 23 of 23 tuned and 12 of 12 held-out phrasings, including negated ones, are right. Changing the check would also risk answers that are now correct. The safeguards that remain are the fenced prompt, the grounding check and the keyword fallback for "unclear". A negation-aware check is the first thing to add if the model ever misreads one.

## D-018. A model outage degrades one answer, fails closed, and is counted

A missing key, a failed endpoint or a spent cap is a `ModelOutage` (`agent/llm.py`). Intent falls back to the keyword rule for that request text, and the row is named in a warning. A document the model could not read keeps its catalog link and is assumed to show the record with identifiers and an active flow, so it can only add findings: no fallback can turn an unread document into a COMPLETE (`tests/test_degrade.py` checks every action). An offline cache miss is a `CacheMiss`, which still stops the run with exit code 2, because in a replay it is a bug, not an outage. Any other caller without a rules path still stops. `cli/audit.py` prints one `degraded:` line with the counts, the caps and the live spend. No answer changed: offline replay is byte-identical. A full run with no key and an empty cache (investigator skipped, since it adds nothing here, D-016) wrote all 518 rows: 518 intents on the keyword rule and 12 documents unread; 516 statuses match the submitted output, 2 COMPLETE became INCOMPLETE, and none became COMPLETE.

## D-019. Spend caps per run, checked before every live call

`ModelClient` refuses a live call, including a JSON repair retry, once the run's estimated cost (token counts times `PRICES`), call count or token total reaches its cap (`limits.py`: $2.00, 5,000 calls, 5,000,000 tokens; `GHOST_MAX_USD`, `GHOST_MAX_CALLS`, `GHOST_MAX_TOKENS` override). The refusal is a `SpendCapReached`, a kind of outage, so D-018 applies. Cache replays cost nothing and are never refused. The final live run used $0.19, 892 calls and 698,660 tokens, so the defaults leave about ten times headroom. With the investigator's 8 threads a run can overshoot a cap by at most the calls already in flight.

## D-020. One new tool: the model chooses where to look in S3, code decides what counts

v1's investigator could only see the files it was handed and changed 0 of 518 answers. `find_ghost_copies` (`agent/tools/s3_ghosts.py`) gives the loop a real system: it lists every version and delete marker under a prefix and reads each version's bytes. The model (`agent/ghost_hunt.py`, native tool calls on the Bedrock chat endpoint) picks folders and identifiers; code matches bytes with the same identifier normaliser as every evidence file, plus email hashes written inside a line. Object text never reaches the model, only key, version id, delete-marker and legal-hold flags, matched and linked identifiers and Comprehend PII types, so a planted instruction has no path to it. Code refuses identifiers that are not the subject's and repeated calls, and after the model finishes it sweeps the scope with any identifier the model left out, so a skipped folder cannot produce COMPLETE. A copy becomes a DELETE decision on that version; a copy under an S3 Object Lock legal hold becomes RETAIN. Measured on the 29-case demo (`demo/results/find.md`): false COMPLETE 16 to 0, 19 of 19 planted copies found by the model's own searches, 0 false findings, 7 of 7 attacks without effect. With no bucket configured nothing runs, and the 518-case replay stays byte-identical.

## D-021. A read-only IAM role, not a user with a key

The tool assumes `ghostdata-agent` (list versions, get object versions and legal holds on one bucket, Comprehend `DetectPiiEntities`) with one role session per case, `ghostdata-<case_id>`. No long-lived secret exists, writes are denied, and CloudTrail data events name the case for every read (`demo/cloudtrail_proof.py`). The agent proposes `delete-object --version-id` commands and never runs them; `demo/run_proposed.py --yes` runs them with a person's own credentials.

## D-022. Chaining follows only identifiers that share a record and belong to no one else

An identifier written in the same JSON object or CSV line as a confirmed match (a reply-to address, an alternate email) may be searched next, unless the identity tables give it to another person. The result tells the model `searchable_next`. Three planted copies hold only such an identifier; the model reached all three. A same-name decoy with different identifiers produces no finding.
