# Ghost Data deletion audit agent

Solution for HackerRank Orchestrate (October 2026), "Ghost Data Still Exists". The full README, with results, architecture and limits, is [`code/README.md`](code/README.md). The challenge brief is [`problem_statement.md`](problem_statement.md).

```bash
python3 code/main.py --offline      # replay recorded model answers and write output.csv
python3 code/main.py                # live run; needs AWS_BEARER_TOKEN_BEDROCK and AWS_REGION
python3 code/evaluation/main.py --offline
```

On the 22 dev samples, trusting the workflow's own status certifies 5 ghosts as deleted; this agent certifies none, gets all 22 statuses right and matches the sample steps with F1 0.958.
