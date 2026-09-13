# Dedicated Codex Home Isolation

V4 uses `/Users/teobun/arc-secure/codex-v4-home` as the explicit Codex home.
It is outside ARC, all benchmark repositories, result/workspace trees, and the
private hidden-test tree. The home is mode `0700`; its non-secret `config.toml`
is mode `0600` and is bound by SHA-256 in the V4 public contract and runtime
lock.

ARC stores only the home path and config path on the Codex agent profile. The
runtime lock recomputes the config digest from the live file and verifies the
path is inside the dedicated home. Provider auth status, provider version
probes, active apparatus probes, native provider terminals, and real provider
subprocesses all receive an explicit `CODEX_HOME` override. The parent shell's
`CODEX_HOME` and ordinary `~/.codex` router catalog cannot replace it.

Authentication files remain vendor-owned and are not hashed, copied, logged, or
packaged. Provider diagnostics expose only the home path, config digest, CLI
identity, environment key names, lifecycle boundaries, and redacted bounded
diagnostic text.

The pinned CLI does not inherit trust from a parent directory: a parent trust
entry was experimentally shown to add per-project entries for nested Git
workspaces. V4 therefore prospectively records exact trust entries for the two
disposable qualification workspaces and the three fixed future `a001` runtime
workspaces. The entries are non-secret, deterministic, and included in the
final config digest. Two real non-benchmark probes completed in separate
pretrusted workspaces with request, response, and completion boundaries while
the hash remained unchanged and no manual restoration was performed.

The runtime also checks the expected and actual `CODEX_HOME`, config path, and
config SHA before and after every repository provider run. Any mismatch is an
explicit apparatus failure and prevents the next repository from starting.

The benchmark's actual task worktrees are nested below study and repetition
directories and include generated names, so exact static trust entries cannot
cover every provider working directory. The final execution strategy is thus
an invocation-scoped snapshot: immediately before each Codex turn ARC copies
only the canonical `config.toml` and vendor-owned `auth.json` into a mode
`0700` temporary home, injects that temporary path explicitly, and removes the
directory in a `finally` block. Codex may mutate this disposable copy; the
canonical config cannot be changed by the provider. ARC never serializes,
hashes, logs, or packages the auth file or the temporary home contents. Every
turn starts from the same canonical config SHA, so B3/B5/B7 have identical
provider configuration starts.

The regression contract creates a broken ambient catalog and a healthy isolated
home. The provider doctor must report the isolated home as authenticated while
the ambient configuration remains broken.
