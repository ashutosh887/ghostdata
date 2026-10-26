# Strands tool: find_ghost_copies

A Strands Agents `@tool` that checks whether a deletion really removed a person from a versioned S3 bucket. It reads every version under a prefix, reports those still holding the person's email, phone or email hash (even behind delete markers) with Comprehend PII types, and proposes `delete-object --version-id` commands. It deletes nothing; legal-hold versions are kept.

Needs Python 3.10+ for Strands. IAM: `s3:ListBucket`, `s3:ListBucketVersions`, `s3:GetObject`, `s3:GetObjectVersion`, `s3:GetObjectLegalHold`, `comprehend:DetectPiiEntities`. Optional `GHOSTDATA_ROLE_ARN` role to assume.

```bash
pip install -r requirements.txt
export AWS_BEARER_TOKEN_BEDROCK=...   # Bedrock API key
python example_agent.py someone@example.net my-bucket exports/
```

The example ran Qwen3 235B via Bedrock's OpenAI-compatible endpoint; Converse was rate-limited. Default Bedrock provider: `Agent(model=BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0"), tools=[find_ghost_copies])` (not run here).

Real output (strands-agents 1.62.0, 26 Oct 2026):

```text
Tool #1: find_ghost_copies
The deletion of mira.okafor@example.net did not fully remove their data from
s3://ghostdata-demo-960149837193/exports/. Two surviving copies were found, both
hidden by delete markers.
1. exports/2026-10/spike-export.csv  version jf5e2hUm...  PII: EMAIL, NAME, PHONE
2. exports/2026-10/spike-export.csv  version zUAbDCat...  PII: EMAIL, NAME, PHONE
```
