# Ablations

Each arm switches off one mechanism (`GHOST_ABLATE`) and reruns the dev samples, the 6 custom cases and all 518
test cases. 'Changed' counts test rows that differ from the full agent's output; 'new COMPLETE' counts test cases
the arm would certify that the full agent reports as INCOMPLETE.

| Arm | Dev false COMPLETE | Dev status | Dev exact | Dev step F1 | Custom exact | Test rows changed | Test new COMPLETE | Validator |
|---|---|---|---|---|---|---|---|---|
| full agent | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 0 | 0 | passed |
| no model: keyword intent, no document reading | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 5 | 4 | FAILED |
| no identity history: current email, phone and hash only | 2 | 20/22 (0.909) | 12/22 (0.545) | 0.897 | 5/6 | 71 | 49 | FAILED |
| no time cut: evidence after audit_at counts | 0 | 21/22 (0.955) | 14/22 (0.636) | 0.913 | 5/6 | 15 | 0 | FAILED |
| no request-time bound on discovery | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.951 | 6/6 | 2 | 0 | passed |
| replica tables ignored | 0 | 22/22 (1.000) | 13/22 (0.591) | 0.950 | 6/6 | 11 | 2 | passed |
| document readings swapped between screenshots | 0 | 22/22 (1.000) | 14/22 (0.636) | 0.958 | 6/6 | 7 | 6 | FAILED |
