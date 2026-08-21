# TB3 medical and freight direct calibration plan

## Purpose

These cells are control-independent direct calibrations. They can narrow the
first failure owner and admit a later family-routed StateM cell, but they do
not by themselves establish score gain.

Both cells use GPT-5.6 Sol at max reasoning, k=1, standard task and environment
build timeout multipliers, Docker, zero retries, and no upload. Neither cell
receives StateM agent environment variables.

## Medical claims processing

- Public Sol Max prior: 0/5 with no reported errors.
- Public mean API cost: $3.82.
- Public resources: 2 CPUs, 10 GB memory, no GPU, 5,400-second agent timeout.
- Platform: AWS x86_64 Docker.
- Agent: `codex-auth-no-session-baseline-v2`.
- Job: `tb3-sol-native-baseline-v2-medical-claims-processing-k1-aws-x86-a`.
- Initial runner PID: `640781`.

The post-result discriminator is limited to public browser/document readiness,
declared artifact production, cross-reference workflow continuity, and small
ATIF metadata. Infrastructure-invalid execution is not a raw zero. A
reward-valid zero admits StateM only when public evidence identifies an
independently replayable family-level owner; task-specific claims decisions or
hidden verifier evidence are never encoded.

## Freight dispatch shift

- Public Sol Max prior: 0/5 with no reported errors.
- Public mean API cost: $5.10.
- Public resources: 2 CPUs, 4 GB memory, no GPU, 7,200-second agent timeout.
- Platform: local ARM64 Docker.
- Agent: `codex-auth-no-session-baseline-v2`.
- Job: `tb3-sol-native-baseline-v2-freight-dispatch-shift-k1-local-arm-a`.
- launchd label: `com.statem.tb3.freight.native.k1.a`.

The local pinned task cache was copied from the AWS audit tree and verified
before launch using relative paths and per-file content digests:

- regular files: 84
- total bytes: 231,929
- deterministic tree SHA256:
  `63529723e98eaea36f68e6ac4ee4b2e22341720bb5eb85ecc72607ea3a2324a1`

The post-result discriminator is limited to public fixed-population identity,
constraint and output structure, stateful CLI lifecycle, artifact production,
and environment validity. Raw zero alone does not authorize a StateM route.

## Advancement rule

For either task, preserve and checksum the direct job first. A later StateM
cell requires a candidate-blind check that is public, independently replayable,
task-general, and owned by a precise existing family/profile. If no such check
exists, park the task as mixed or capability-limited instead of spending a
search cycle. Adapted cells remain separate from fresh score evidence.
