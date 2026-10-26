# Strands tool: find_ghost_copies

A [Strands Agents](https://strandsagents.com) `@tool` that checks whether a deletion really removed a person from a versioned S3 bucket. It reads every version under a prefix and reports the ones that still hold the person's email, phone or email hash, including versions hidden behind delete markers. Each match comes with the PII types Amazon Comprehend finds and a proposed `delete-object --version-id` command. The tool deletes nothing, and it never proposes deleting a version under legal hold.

## Requirements

- Python 3.10+ (Strands needs it)
- IAM permissions `s3:ListBucket`, `s3:ListBucketVersions`, `s3:GetObject`, `s3:GetObjectVersion`, `s3:GetObjectLegalHold` and `comprehend:DetectPiiEntities`
- Optional: set `GHOSTDATA_ROLE_ARN` to read through a read-only role

## Run

```bash
pip install -r requirements.txt
export AWS_BEARER_TOKEN_BEDROCK=...   # Bedrock API key
python example_agent.py someone@example.net my-bucket exports/
```

`example_agent.py` runs Qwen3 235B through Bedrock's OpenAI-compatible endpoint. To use the default Bedrock provider instead, pass a `BedrockModel`. I have not run that variant.

```python
from strands import Agent
from strands.models import BedrockModel

agent = Agent(model=BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0"), tools=[find_ghost_copies])
```

## Output

A real run (strands-agents 1.62.0, 26 Oct 2026):

```text
Tool #1: find_ghost_copies
The deletion of mira.okafor@example.net did not fully remove their data from
s3://ghostdata-demo-960149837193/exports/. Two surviving copies were found, both
hidden by delete markers.
1. exports/2026-10/spike-export.csv  version jf5e2hUm...  PII: EMAIL, NAME, PHONE
2. exports/2026-10/spike-export.csv  version zUAbDCat...  PII: EMAIL, NAME, PHONE
```
