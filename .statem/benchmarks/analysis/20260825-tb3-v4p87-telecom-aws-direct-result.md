# TB3 v4p87 Telecom repeated direct result

## Result

- Evidence class: repeated direct platform calibration; not fresh score evidence.
- Raw reward: `1.0`; reward and protocol valid.
- Errors / retries: `0 / 0`.
- Model / agent: GPT-5.6 Sol max, direct baseline-v2, Codex `0.149.1`.
- Platform: AWS x86_64 Docker, standard task timeout.
- Cost: `$4.735711`.
- Tokens: 6,638,280 input; 6,449,408 cached; 70,023 output.
- Wall / agent time: about 43.3 / 41.2 minutes.
- ATIF: `ATIF-v1.5`, 90 steps; raw-session paths absent.
- Public artifact: the declared customer-cluster JSON was collected successfully.

The direct route is reward-positive on AWS, but this is not a fresh gain. An
earlier Daytona x86 direct cell using the same model, Codex version, and agent
already completed with valid raw `1.0`. The v4p87 preregistration's fresh label
missed that preserved result. This run supplies cross-runtime non-regression
and lower observed API cost, not an additional fresh conversion.

## Routing decision

Freeze the direct route and do not create a StateM arm or extract a family
control. Record the duplicate as a hyper-level prelaunch history-check defect:
task, model, Codex version, agent, and prior reward/protocol status must be
resolved before assigning a fresh evidence class.

## Preservation

- Remote/local regular files: `14 / 14`.
- Remote/local bytes: `5,639,570 / 5,639,570`.
- Deterministic relative-path/content tree SHA256:
  `2000fc1bce762e313bdc373468e21427c7312652635165ac136649c023f9f570`.
- Remote-to-local checksum dry-run: empty.
- Runner, Harbor, verifier, tmux session, and task containers: exited.

Backup:
`.statem/benchmarks/backups/tb3-sol-native-baseline-v2-telecom-entity-v4p87-k1-aws-x86-b`
