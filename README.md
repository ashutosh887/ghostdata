# Ghost Data

An agent that checks whether personal data is really deleted.

A deletion workflow said Elena's data was gone. Her export was still in S3, one version behind a delete marker. Ghost Data v1 believed the workflow. v2 reads every version in the bucket, finds the file, and answers INCOMPLETE with the version id and the command that removes it.

I tested it on 29 made-up customers. The workflow had marked 27 of them deleted.

| | v1 | v2 |
|---|---|---|
| False COMPLETE | 16 | 0 |
| Correct status | 13 of 29 | 29 of 29 |
| Surviving copies found | 0 of 19 | 19 of 19 |
| False findings | 0 | 0 |
| Truly deleted or look-alike customers left COMPLETE | 11 of 11 | 11 of 11 |
| Legal-hold copies kept | | 2 of 2 |
| Planted prompt attacks that changed a verdict | | 0 of 7 |
| Cases proven COMPLETE after the proposed deletes ran | | 27 of 27 |

These come from live runs on Amazon Bedrock and S3, all in `demo/results/`. [`find.md`](demo/results/find.md) is the audit, [`run_proposed.txt`](demo/results/run_proposed.txt) is me running the deletes it proposed, and [`prove.md`](demo/results/prove.md) is the audit again afterwards. [`cloudtrail.json`](demo/results/cloudtrail.json) has a CloudTrail event for every read.

## Try it

The recorded run replays with no AWS account and no key.

```bash
python3 cli/demo.py --recorded
```

To run it live in your own account you need Python 3.9+, boto3 and a Bedrock API key.

```bash
aws s3api create-bucket --bucket my-ghost-demo --object-lock-enabled-for-bucket
export GHOSTDATA_S3_BUCKET=my-ghost-demo AWS_BEARER_TOKEN_BEDROCK=...
python3 demo/seed_bucket.py --reset
python3 cli/demo.py
```

The seed script writes the 29 customers' exports, CRM syncs, backups, delete markers and legal holds. `demo.py` audits every case with the tool off and then on, and scores both against what was planted. Set `GHOSTDATA_ROLE_ARN` to make the reads go through a read-only role, then `demo/cloudtrail_proof.py` lists the CloudTrail event for each one.

## How it works

v1 reads a deletion request, collects every email, phone and email hash the person has ever used, follows them through the evidence files it's given, and applies the deletion rules. It answers COMPLETE, INCOMPLETE or NOT_APPLICABLE with cited steps. It never looked anywhere else.

v2 adds one tool, `find_ghost_copies(prefix, identifiers)`. It lists every version and delete marker under a prefix and reads each version. For each version holding one of the identifiers it returns the key, the version id, whether a delete marker hides it, whether an Object Lock legal hold protects it, any other identifiers in the same record, and the personal-data types Amazon Comprehend finds near the match.

The model picks which folders to search and with which identifiers. Code decides what counts. A copy counts only if the identifier is in the bytes S3 returned for that exact version id. The model never sees object text, only those fields. Code refuses identifiers that belong to someone else and refuses repeated calls. When the model finishes, code searches any folder it skipped.

I also ran it with the model switched off. Code's sweep alone gets the same 29 of 29, in 240 folder searches ([`find-no-model.md`](demo/results/find-no-model.md)). With the model on, it searched every folder itself and the sweep had nothing left to do. So the code checks are what make it correct. The model plans the search and explains it.

Each copy becomes three steps, REPORT_REMAINING_RECORD, DELETE_RECORD and VERIFY_RECORD_ABSENT. A copy under legal hold becomes VERIFY_RECORD_PRESENT. The agent prints `aws s3api delete-object --version-id ...` for each copy and never runs it.

[`integrations/strands/`](integrations/strands/) has the same tool as a Strands Agents `@tool`, with a 16-line example agent.

## AWS services

| Service | Used for |
|---|---|
| Amazon Bedrock | Qwen3 235B reads the request and runs the search with native tool calls |
| Amazon S3 | `ListObjectVersions`, `GetObject` by version id, `GetObjectLegalHold` |
| Amazon Comprehend | `DetectPiiEntities` on the text around each match |
| AWS IAM | Role `ghostdata-agent`, read-only on one bucket, with `s3:ListBucket`, `s3:ListBucketVersions`, `s3:GetObject`, `s3:GetObjectVersion`, `s3:GetObjectLegalHold` and `comprehend:DetectPiiEntities` |
| AWS CloudTrail | One event per read, under a role session named after the case |

## What changed from v1

| | v1.0.0 | v2.0.0 |
|---|---|---|
| Where it looks | evidence files | evidence files and every version in an S3 bucket |
| Tool calls | one flat JSON schema | native tool calls, one schema per tool |
| Repeated calls, other people's identifiers | the prompt asks the model not to | code refuses them |
| Model down or key missing | the run stops | that row falls back to rules |
| Spend | no cap | caps per run |
| Regression check | false COMPLETE only | any drop in any score |
| Answers the agent loop changed | 0 of 518 | 16 of 29 |

## Limits

- It only looks in S3. Databases and other stores would need their own tools.
- An unversioned bucket has no old versions to find.
- It reads text up to 1 MB per version. Bigger or unreadable versions are listed as skipped and don't change the verdict. It doesn't parse Parquet or other binary formats.
- It proposes deletes. A person runs them.

## Dataset

I first built it for a public deletion-audit challenge's problem statement (HackerRank Orchestrate, October 2026): https://github.com/interviewstreet/hackerrank-orchestrate-october26. That dataset isn't in this repo. `sh scripts/get_dataset.sh` downloads it, and running v1 on it needs a Bedrock key. The S3 demo uses only the made-up customers in `demo/`.

## More

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) covers the architecture, how a case is decided, and the evaluation.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) and [`docs/FAILURES.md`](docs/FAILURES.md) list the choices and what went wrong, with numbers.
