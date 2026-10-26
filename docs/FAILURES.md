# Failures

Each entry: wrong behaviour, root cause, fix, and the measured effect.

## F-001. Citations pointed at evidence captured after audit_at

- Wrong: cases 21, 23, 24, 25 to 29 cited `evidence_02`, a snapshot bundle captured on 17 Sep, for audits dated 15 Sep 12:00. The sample answers cite `evidence_92`, a read-back captured at 11:44 that day.
- Cause: the state function kept only the proofs at the newest timestamp. The bundle's inner snapshot is stamped exactly 12:00, so it was the only candidate, and the citation rule never saw the earlier source.
- Fix: keep every observation that agrees with the final value since the last one that disagreed, then cite the newest one whose file existed by `audit_at`.
- Effect (dev, 22 cases): exact 9 to 13 together with F-002; step F1 0.748 to 0.954; evidence field accuracy 0.716 to 0.933.

## F-002. Keyword intent missed "I'm deleting my account"

- Wrong: case_04 and case_12 came out NOT_APPLICABLE. Their texts say "I'm deleting my account" and "before deleting it".
- Cause: the deletion word list had the base and past forms only.
- Fix: add the -ing forms. This is a patch on the keyword baseline (arm A). Phrasing like this is why intent goes to a model in phase 5.
- Effect: status 20/22 to 22/22.

## F-003. Unknown state passed as compliant

- Wrong: the first full run marked 6 screenshot cases (33, 39, 46, 50, 55, 61) COMPLETE with verification steps that cited nothing. The validator rejected the file.
- Cause: a record seen only in a screenshot or PDF had no observation the state function could use, so "not violated" was the default, and "unknown" read as "fine".
- Fix: (1) each catalog link is tied to the newest earlier document that shows its display reference, so 12 resources gain a dated observation; (2) a record with no observation at all falls back to the latest full capture of its system before `audit_at`; (3) a decision with no proof is flagged `unverified`.
- Effect: 6 cases with uncited COMPLETE steps down to 2 (case_39, a connector console, and case_55, a restore console). Their state is printed on screen, which is what the vision step in phase 5 reads.

## F-004. A queue-order rule that the data does not support

- Wrong: v3 tied anonymised analytics records to cases by assuming the deletion worker handles a batch in the same order for every operation type. It fixed case_27 and case_28 on dev (15/22 exact).
- Check: the same assumption can be tested on accounts whose owner is known through an identity link. Ranking cases by their first linked worker operation predicts the order of their account deletes in 10 of 23 pairs. Ranking by request time predicts it in 27 of 54. Both are coin flips.
- Fix: keep only the forced case, one eligible request and one unowned anonymisation in a batch (case_04's analytics_901). Multi-case batches stay unassigned.
- Effect: dev exact 15/22 to 14/22, step F1 0.966 to 0.958, false COMPLETE still 0. A rule that is right by luck on two dev cases would be wrong about half the time on the hidden ones, and I could not defend it.

## F-005. Corrections and hypotheticals read as deletion

- Wrong: on 23 hand-written phrasings outside the dataset, the model said yes to "Please delete the old shipping address from my profile and use the new one", and "unclear" to "I'm thinking about deleting my account; what would happen...", where the keyword fallback then said yes.
- Cause: the intent prompt listed corrections only as "correct or change a detail", so deleting one field to replace it looked like deletion, and it said nothing about questions about deletion.
- Fix: two lines in `intent.md`: deleting one detail to replace it is a correction, and asking what deletion would do is a question. Only a present request is `yes`.
- Effect: tuned probes 21/23 to 23/23; 12 held-out probes written after the fix and run once, 12/12 (keywords alone 9/12). Dev unchanged (status 22/22, step F1 0.958) and 0 of 518 test rows changed.

## F-006. The evaluation report said "not run" for the custom cases

- Wrong: after F-005 changed the intent prompt, `report.py --offline` wrote "Result: not run exact" for the custom cases and dropped their run output, and that report was committed.
- Cause: the custom-case texts had no cached intent answer under the new prompt, so `custom.py --offline` stopped, and `report.py` ran it without checking the exit code, so the failure became a sentence in the report.
- Fix: run the custom cases live once to record their answers, and run every scorer in `report.py` with `check=True`, so a failed scorer stops the report.
- Effect: report back to 6/6 exact. Found by the end-to-end checklist in the session notes.

## F-007. One unknown email stopped the whole run

- Wrong: a deletion request whose email matched no identity raised an error in the resolver, so no output was written for any of the other cases. An `audit_at` before the request produced a COMPLETE whose check cited nothing. Found by the independent review with hand-made requests. No dataset request does either.
- Cause: the resolver treated a missing subject as a crash, and nothing checked that a request's times were in order.
- Fix: a request that cannot be audited, because its email matches no identity (CONTRACT I5) or its `audit_at` is before `requested_at` (I6), is written as `NOT_APPLICABLE` with a warning and a case note, and the other cases still run. A first version rejected the whole file on a bad time order; a second-model review caught the inconsistency. A missing model answer and a missing OCR tool end with one clear message and exit code 2. Other errors keep their traceback. Five tests in `tests/test_requests.py`.
- Effect: none of the 518 answers changed. An adversarial file with one unknown email now yields its row and a warning instead of no file.

## F-008. Most investigations ran out of rounds

- Wrong: 57 of the 121 flagged investigations used all 6 rounds without concluding.
- Cause: the prompt said when to declare a case unresolvable but not when to stop, so the model kept repeating lookups on account ties.
- Fix: a stop rule in `investigator.md`: stop once the flag is settled, declare a tie with no identifier evidence unresolvable, and never repeat a call.
- Effect: 64 to 119 of 121 investigations reach a conclusion, 0 hit the round limit, and 0 of 518 answers changed.

## F-009. A same-time tie could keep the state and drop its proof

- Wrong: when two sources at the same newest time disagreed, one showing the record and one omitting it, `latest()` in `state.py` correctly chose present but returned no proof, so the finding would have no evidence to cite. The validator also only warned when a step cited evidence captured after `audit_at`. Found by an independent read-only review with a hand-made tie. Neither happens in the dataset.
- Cause: the last disagreeing time was taken over all events, including the tie itself, so every agreeing proof at that time was filtered out. The late citation check was written as a warning before F-001 made the rule strict.
- Fix: the last disagreement is taken only from times before the newest, and a citation after `audit_at` is now a validator error. Four tests in `tests/test_state.py` and `tests/test_validate.py`; the tie test fails on the old code.
- Effect: none of the 518 answers changed; offline replay is byte-identical and the validator still reports 0 errors and 0 warnings.

## F-010. The release gate only required 0 false COMPLETE

- Wrong: `check.py` passed as long as the dev set had 0 false COMPLETE and every status right, so a change that lost exact matches, step F1 or field accuracy shipped without a failure. A missing key or a model outage also stopped the whole run (D-018).
- Cause: the gate checked safety but not quality, and every model error was fatal.
- Fix: `evaluation/baseline.json` pins the offline dev score (status, exact match, step F1, sequence order and similarity, and accuracy per field); `check.py` fails on any drop from it and on any false COMPLETE. `check.py --pin` records a new baseline and refuses one with a false COMPLETE. Seven tests in `tests/test_gate.py` feed synthetic drops; each one fails the gate. Outages degrade per D-018 and D-019, with 14 tests in `tests/test_degrade.py`.
- Effect: none of the 518 answers changed; offline replay is byte-identical. The gate passes at the pinned 14/22 exact and 0.958 step F1. Field accuracy is pinned at the scorer's three decimals, so a drop smaller than 0.001 is not caught.

## F-011. Cut-off tool-call arguments broke every second turn of the S3 hunt

- Wrong: in the first live demo run every one of the 27 hunts ended "model unavailable", and the code sweep found what the model missed: 11 of 19 copies came from the model's own searches.
- Cause: the model issued about seven searches in one turn and ran out of its 600 output tokens, so the last call's JSON was cut off. The loop echoed the broken arguments back in the history, and the endpoint rejected the next turn with HTTP 400.
- Fix: 2,000 output tokens per turn; malformed arguments are echoed back as `{}` and the call is refused with a message asking for fewer identifiers per call.
- Effect: 27 of 27 hunts end with the model calling `finish`, 0 degrade, and 19 of 19 copies come from the model's own searches.

## F-012. Email hashes written inside a line were not matched

- Wrong: with code sweeping alone, 15 of 19 planted copies were found; the three hash cases (a JSONL feature file, a backup of hashes) were missed.
- Cause: the shared normaliser only reads a hash when it is the whole value.
- Fix: the S3 tool also collects 64-hex runs inside text (`text_keys`); v1's evidence matching is unchanged. Test `test_hash_inside_a_line_is_found`.
- Effect: 19 of 19 found; 518-case replay byte-identical.

## F-013. A recorded demo could not replay its own run

- Wrong: `demo.py --recorded` stopped on a cache miss for a model turn.
- Cause: recordings are written with sorted keys but live tool results kept S3's order, so the replayed tool result differed by key order and the turn's cache key changed.
- Fix: every tool result is serialised with sorted keys and folder listings are sorted, so live and replay produce the same bytes.
- Effect: the recorded replay reproduces the live report.
