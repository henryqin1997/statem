# TB3 v4p80 KV matched pair auth-invalid attempt

Both preregistered arms ended before task execution with
`NonZeroAgentExitCodeError`. Codex model discovery returned HTTP 401 with
`token_invalidated` for the stale remote ChatGPT auth file. Both jobs record
zero retries, no token or cost accounting, and no model-capability evidence.
The displayed raw zeros are invalid for reward and scope attribution.

The current local auth file was copied atomically to the remote host without
reading or logging its contents. Local and remote file SHA256 values match. One
replacement pair with distinct job ids is authorized because the diagnosed
infrastructure boundary changed; ordinary task failures remain non-retryable.

Preservation:

| Arm | Files | Bytes | Tree SHA256 |
| --- | ---: | ---: | --- |
| direct | 14 | 56,334 | `1cd6d353ca4f1630c7fa1151c8147267621a18f6952bec1cda73079a73973464` |
| StateM | 22 | 126,168 | `0876bb8c29c06f07cacd790a519defd3df87cc9e29361cd1c70665614c517d7a` |

Remote source and local backup match in count, bytes, deterministic relative
path/file-digest tree hash, and empty recursive checksum dry-run for both arms.
