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

## What goes where

| Path | Git | In `code.zip` | Why |
|---|---|---|---|
| `code/` except `code/cache/` | committed | yes | the solution |
| `code/cache/` | ignored | yes | recorded model and OCR answers; `--offline` cannot run without them |
| `README.md`, `CLAUDE.md`, `.gitignore` | committed | no | the root README mirrors `code/README.md` |
| `AGENTS.md`, `problem_statement.md`, `agent_trace_instructions.md`, `dataset/` | committed, never edited | no | organisers' files |
| `output.csv` | ignored | no | uploaded on its own |
| `log.txt` | ignored | no | uploaded on its own as the chat transcript |
| `notes/` | ignored | no | private working notes: session summaries, reviews, interview prep, decision trail |
| `.env` | ignored | no | the key; never printed, logged, committed or zipped |
| `code.zip`, `__pycache__/`, `.venv/` | ignored | no | build output |

Scratch output goes to `/tmp` or the session scratchpad. Anything worth keeping goes to `notes/`, never to a folder outside the repo. Before every commit, `git status --short` must show only files you meant to add; a `??` file under `code/` is either committed on purpose or deleted.

## Before committing

```bash
python3 code/evaluation/check.py                   # runs every gate below plus custom cases and probes
python3 -m unittest discover -s code/tests
python3 code/evaluation/main.py --offline          # dev score must not regress
python3 code/main.py --offline --out /tmp/o.csv && cmp output.csv /tmp/o.csv
```

The root `README.md` is the full `code/README.md` with paths from the repo root. Change both together.

Commit only source, tests, prompts and docs, by explicit path. `log.txt`, `output.csv` and `code/cache/` stay out of git. Commit messages are short conventional commits with no trailers. Record a new rule in `CONTRACT.md`, a choice in `DECISIONS.md` and a fix in `FAILURES.md` with its before and after numbers.
