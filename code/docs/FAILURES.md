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
