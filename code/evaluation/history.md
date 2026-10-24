# Evaluation history

One row per pinned scorer run on the sample cases.

| When (UTC) | Label | System | Split | Cases | False COMPLETE | Status | Exact | Step F1 | F1 no evidence | Order ok |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-24 14:34 | baseline: trust the workflow claim | trust_workflow | dev | 22 | 5 | 14/22 (0.636) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:34 | baseline: always INCOMPLETE | always_incomplete | dev | 22 | 0 | 15/22 (0.682) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:34 | placeholder: all NOT_APPLICABLE | resolver | dev | 22 | 0 | 0/22 (0.000) | 0/22 (0.000) | 0.000 | 0.000 | 22/22 (1.000) |
| 2026-10-24 14:42 | resolver v1: rules intent, identity links, state at audit_at | resolver | dev | 22 | 0 | 20/22 (0.909) | 9/22 (0.409) | 0.748 | 0.929 | 22/22 (1.000) |
| 2026-10-24 14:43 | v2: proofs since last change; -ing deletion verbs | resolver | dev | 22 | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.954 | 0.954 | 22/22 (1.000) |
| 2026-10-24 14:44 | v3: anonymised analytics by worker queue order when counts match | resolver | dev | 22 | 0 | 22/22 (1.000) | 15/22 (0.682) | 0.966 | 0.966 | 22/22 (1.000) |
| 2026-10-24 14:50 | v4 agent: model intent + document reading | agent | dev | 22 | 0 | 22/22 (1.000) | 15/22 (0.682) | 0.966 | 0.966 | 22/22 (1.000) |
