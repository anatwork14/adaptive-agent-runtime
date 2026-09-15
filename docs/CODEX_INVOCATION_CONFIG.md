# Codex invocation configuration qualification

This document records the apparatus qualified before any V10 campaign exists.
It does not change V5–V9 source, contracts, or preregistration.

## Pinned lifecycle findings

The pinned executable is `codex-cli 0.133.0-alpha.1`.

```text
CODEX_HOME
 ├── config.toml       user/runtime configuration; mutable
 ├── auth.json         file-backed ChatGPT/OpenAI authentication; separate file
 ├── logs, sessions,
 │   state, cache       runtime state; not scientific inputs
 └── skills/plugins     provider-local/runtime state
```

The pinned CLI behavior was established from its local `--help`, binary strings,
the ARC subprocess environment, and non-inference execution:

- `CODEX_HOME` selects the Codex home. The effective user configuration is
  `${CODEX_HOME}/config.toml`; the normal default is the user's Codex home.
- File-backed authentication is read from `${CODEX_HOME}/auth.json`. ARC must
  therefore provide authentication in a disposable runtime home when the
  scientific snapshot is staged elsewhere.
- `--config key=value` is a runtime override, not a file selector.
- `--profile-v2 name` layers `${CODEX_HOME}/name.config.toml`; it is not an
  independent authentication location.
- `--ignore-user-config` skips `${CODEX_HOME}/config.toml` but still uses
  `CODEX_HOME` for authentication. It cannot serve as the scientific snapshot
  mechanism.
- TUI initialization can persist configuration state. The observed V9 drift
  coincided with creation of `config.toml` and `.personality_migration` and with
  project-trust interaction. `trust_level` entries are therefore not a safe
  hidden dependency.
- Model selection is represented in `config.toml` and is also exposed by the
  TUI. Reasoning effort is a supported config field and was previously supplied
  by ARC as a `--config` override.

The pinned CLI exposes no supported separate auth-path option in its help. The
qualified separation is consequently: preserve the scientific snapshot as a
campaign artifact, copy its exact bytes into a disposable `CODEX_HOME`, and
copy the authenticated `auth.json` only into that disposable runtime home.
The auth copy is never placed in the snapshot, sidecar, manifest, Git, or
preregistration. Symlink-based auth separation is not used.

Authoritative upstream references for the corresponding Codex mechanisms:

- [Codex configuration schema](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json)
- [Codex configuration loader](https://github.com/openai/codex/blob/main/codex-rs/config/src/loader/mod.rs)
- [Codex auth storage](https://github.com/openai/codex/blob/main/codex-rs/login/src/auth/storage.rs)

These upstream references are supplementary; the pinned local CLI behavior is
the qualification authority for this apparatus.

## Configuration field classification

The default is `UNKNOWN`; an unclassified field must be treated as potentially
scientific and excluded from a future snapshot until qualified. The table uses
the field names observed in the live pinned Codex configuration and its local
schema strings. `projects.<path>.trust_level` is shown as a family because its
key contains a machine/project path.

| Field or family | Classification | Qualification decision |
|---|---|---|
| `model` | `SCIENTIFICALLY_FROZEN` | Freeze exactly; changes the model treatment. |
| `model_reasoning_effort` | `SCIENTIFICALLY_FROZEN` | Freeze exactly; changes the reasoning treatment. |
| `model_provider`, `model_providers.*` | `SCIENTIFICALLY_FROZEN` | Freeze or reject unless the provider identity is fixed outside the file and validated. |
| `approval_policy`, `sandbox_mode`, `default_permissions`, `permission_profile` | `SCIENTIFICALLY_FROZEN` | Freeze the effective invocation policy; do not infer equivalence from a UI label. |
| `shell_environment_policy.*`, `network.*`, `web_search*`, `oss_provider`, `transport` | `SCIENTIFICALLY_FROZEN` | Freeze when present because they can change tools, network, or provider behavior. |
| `model_context_window`, `model_auto_compact_token_limit*`, `model_verbosity`, `model_reasoning_summary` | `SCIENTIFICALLY_FROZEN` | Freeze when effective; otherwise record an explicit exclusion. |
| `personality` | `SCIENTIFICALLY_FROZEN` | Freeze or explicitly set a fixed value; it can alter model-facing instructions and outputs. |
| `projects.<path>.trust_level` | `UNKNOWN` | Treat as potentially tool-affecting; normalize or explicitly exclude with a tested trust strategy. |
| `hooks.*`, `mcp_servers.*`, `plugins.*`, `marketplaces.*` | `UNKNOWN` | Treat as potentially tool/network-affecting; exclude from the minimal snapshot unless qualified. |
| `forced_login_method`, `auth_credentials_store` | `AUTH_ONLY` | Never freeze credential bytes; validate supported auth state separately. |
| `mcp_oauth_credentials_store` | `AUTH_ONLY` | Never freeze OAuth credentials or credential files. |
| `notify`, `desktop.*`, `tui.*`, `keybindings`, display/conversation settings | `MUTABLE_UI_STATE` | Exclude; these are interactive presentation state unless a field is proven model-facing. |
| `check_for_update_on_startup`, analytics/update notices | `MUTABLE_UI_STATE` | Exclude from scientific identity. |
| `model_catalog_json`, model availability/cache entries | `CACHE/EPHEMERAL` | Do not freeze catalogs as treatment; validate the pinned model separately. |
| `CODEX_HOME`-resident logs, sessions, SQLite state, plugin caches, installation metadata | `CACHE/EPHEMERAL` | Never include in a scientific snapshot. |
| `source_type`, `source` under marketplace configuration | `PROJECT_LOCAL_STATE` | Exclude unless the exact marketplace/plugin is an experimental dependency. |
| `features.*`, `memories.*`, `agents.*` | `UNKNOWN` | Qualify each enabled feature before inclusion; default to exclusion. |
| any field not listed above | `UNKNOWN` | Fail closed for a future freeze until classified and justified. |

The qualification implementation deliberately emits only `model` and
`model_reasoning_effort`, the two fields present in the V8/V9 experimental
command contract. Provider, approval, sandbox, network, trust, and tool policy
must be carried in the future semantic projection and effective argv contract
only after their pinned representation is separately qualified.

## Qualified architecture

```text
interactive user CODEX_HOME
        │
        └── auth status/setup only

campaign-owned snapshot
        │
        ├── config.toml                exact UTF-8 bytes
        ├── config.toml.sha256         exact digest sidecar
        └── config-manifest.json       non-secret semantic projection
                    │
                    ▼
        disposable invocation CODEX_HOME
        ├── copied exact config.toml
        └── runtime-only copied auth.json
                    │
                    ▼
        verify source and staged digest immediately before Codex invocation
```

`runtime.codex_invocation_config` implements this boundary through the
`CodexInvocationConfig` object, `create_snapshot`, `verify_snapshot`, and
`stage_invocation_home`. Snapshot serialization is UTF-8, newline-terminated,
sorted by key, timestamp-free, and contains no credentials. Verification checks
bytes, size, sidecar, manifest, TOML parse, and semantic projection. Missing,
corrupt, or mismatched snapshots raise `ConfigContractError` before a provider
process may be started.

The staged home copies exact snapshot bytes and runtime-only authentication.
The source snapshot remains authoritative; staging is not a replacement for
pre-invocation verification.

## Scratch qualification

The non-campaign scratch artifacts are at:

`/Users/teobun/arc-study/apparatus/codex-config-isolation-test/`

They contain two snapshots with identical model and different reasoning
settings, each with `config.toml`, `config.toml.sha256`, and
`config-manifest.json`. No V10 preregistration or freeze directory exists.

No V10 campaign consumes this module yet. Integration into a future campaign
must add the object to the frozen runtime contract and invoke verification after
staging and immediately before the provider subprocess.
