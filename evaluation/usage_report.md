# Token usage and cost

Final full-dataset run that wrote `output.csv`: 518 requests, 2026-10-25 05:07 UTC.
Provider: Amazon Bedrock (OpenAI-compatible endpoint). Every answer was requested live in this run (cache reads off), then stored in
`cache/` so `python3 cli/audit.py --offline` replays it with no key and no cost.

## Per model

| Model | Roles | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) | Price in / out per 1M |
|---|---|---|---|---|---|---|---|
| `qwen.qwen3-235b-a22b-2507` | intent, investigator | 880 | 628,457 | 42,411 | 670,868 | 0.1756 | 0.22 / 0.88 |
| `qwen.qwen3-vl-235b-a22b-instruct` | vision | 12 | 26,747 | 1,045 | 27,792 | 0.0170 | 0.53 / 2.66 |
| **All models** | | **892** | **655,204** | **43,456** | **698,660** | **0.1925** | |

## Per role

| Role | Calls | Input tokens | Output tokens | JSON repairs | Failures |
|---|---|---|---|---|---|
| intent | 398 | 193,466 | 22,039 | 0 | 0 |
| investigator | 482 | 434,991 | 20,372 | 0 | 0 |
| vision | 12 | 26,747 | 1,045 | 0 | 0 |

## Per request

- Total tokens: 698,660; average per request: 1,349.
- Estimated cost: $0.1925 in total; $0.000372 per request.
- Model calls: 892 in total; 1.72 per request.
- Intent is classified once per distinct request text; documents are read once each; the investigator runs only
  on the 121 cases the resolver flagged, at most 6 rounds each.

Costs are estimates: the endpoint returns token counts but no price, so the table applies the Amazon Bedrock
on-demand prices listed in `src/ghostdata/config.py`.
