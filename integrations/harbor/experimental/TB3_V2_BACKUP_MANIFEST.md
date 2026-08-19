# Terminal-Bench 3 V2 Backup Manifest

Recorded 2026-08-19 in `/Users/qinziheng/workspace/statem`.

| Snapshot | Regular files | Total bytes | Deterministic relative-path tree SHA-256 |
| --- | ---: | ---: | --- |
| `.statem/backups/tb3-v2-controls-prechange-20260819/` | 11 | 246,951 | `da47ee3fa50f38ad35089c043d5687f7b6e43637b3a3585aa301599e0bd2e75a` |
| `.statem/backups/tb3-v2-controls-postchange-20260819/` | 14 | 307,749 | `4541229b7da206022c8fcbabefd9c86ffb1a0a6572586e1fed260e5de7bd6b70` |

The tree hash is computed from lexicographically sorted regular-file paths and
their SHA-256 digests relative to each snapshot root. The manifest is kept
outside both snapshot trees so recording the checksum cannot change the tree it
describes.

The post-change source-to-snapshot checksum dry run reported no differences.
The private GitHub branch is an additional off-machine backup; it contains code,
tests, and design records only, never benchmark sessions, credentials, provider
configuration, or raw trajectories.
