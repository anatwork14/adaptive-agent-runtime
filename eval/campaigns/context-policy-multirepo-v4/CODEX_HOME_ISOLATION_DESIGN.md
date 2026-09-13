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

Codex may add a transient project-trust stanza when first used in a disposable
probe workspace. The qualification procedure restores the minimal config after
that probe and records the final digest before any V4 freeze; the transient
workspace entry is therefore not part of the frozen provider identity.

The regression contract creates a broken ambient catalog and a healthy isolated
home. The provider doctor must report the isolated home as authenticated while
the ambient configuration remains broken.
