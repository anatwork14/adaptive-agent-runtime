# Frozen Private Hidden-Suite Digests

The exact hidden-test bytes are intentionally not committed to this public repository. These digests identify the private bundle authored for `context-policy-multirepo-v1` and allow the operator to fail closed before preregistration.

ARC `tree_digest()` values for the extracted repository subdirectories:

| Repository suite | Expected tree digest |
|---|---|
| `click/` | `6d28fff3d4d70b655c0294cf80175d75a403b9cde6762ec9b2f7bc149906f3d3` |
| `httpx/` | `771e5afa152bcc41676fe173aad7809485eb5cccdcaf312865b2f6dd2a798334` |
| `python-dotenv/` | `950297bdebad5f5e2560ec8406e6f80ca289e6cc6672a3e9648a814a55284bb7` |

The original private ZIP distributed to the study operator has SHA-256:

`6940cf0bb406153fb9a5e11c2260fba7951e4b101d582cd16d035a92aabd3d6e`

Before calling `arc benchmark preregister`, compute ARC's tree digest for the corresponding extracted directory and require an exact match to this table. Do not run pytest in-place in the frozen hidden directory before preregistration if that would create cache/bytecode files there; either disable bytecode/cache generation or test a disposable copy. The preregistration digest covers every file in the directory recursively.
