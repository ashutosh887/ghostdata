@AGENTS.md

# Working on this repo

AGENTS.md owns the challenge contract and the log format. These are the conventions this solution adds.

## Layout

- `code/main.py` runs all 518 cases and writes `output.csv`. `code/explain_case.py <case_id>` traces one case.
- `code/audit/ingest/` reads evidence into observations (facts with a time) and snapshots (full captures). Activity rows are claims and stay separate.
- `code/audit/{identity,state,policy,planner,resolver}.py` decide every status, step and citation.
- `code/audit/agent/` holds the model client, the intent classifier, the document reader and the investigator. Prompts are Markdown files in `code/audit/agent/prompts/`.
- `code/evaluation/` scores against the samples, runs the custom cases and the ablations.
- `code/docs/CONTRACT.md`, `DECISIONS.md`, `FAILURES.md` record the rules, the choices and what went wrong.

## Rules

- The model reads; code decides. A model answer is used only after code checks it against the evidence.
- No hardcoded case ids, user ids, labels or file-specific answers. No timing patterns from how the data was generated.
- Use only information at or before each case's `audit_at`.
- Never use the 10 holdout samples in `code/evaluation/splits.py` for tuning. Score the holdout once, at the end.
- Read keys from the environment or an uncommitted `.env`. Never print or log them.
- Python 3.9+, standard library only. No comments unless the code cannot say it.

## Before committing

```bash
python3 code/evaluation/check.py                   # runs every gate below plus custom cases and probes
python3 -m unittest discover -s code/tests
python3 code/evaluation/main.py --offline          # dev score must not regress
python3 code/main.py --offline --out /tmp/o.csv && cmp output.csv /tmp/o.csv
```

The root `README.md` is the full `code/README.md` with paths from the repo root. Change both together.

Commit only source, tests, prompts and docs, by explicit path. `log.txt`, `output.csv` and `code/cache/` stay out of git. Commit messages are short conventional commits with no trailers. Record a new rule in `CONTRACT.md`, a choice in `DECISIONS.md` and a fix in `FAILURES.md` with its before and after numbers.
