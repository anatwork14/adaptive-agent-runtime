# V6 ChatGPT Subscription Authentication

V6 uses the already-qualified ChatGPT subscription-backed Codex home. The
cancelled API-key workflow is not part of V6 and no API-key credential is
requested, persisted, or used.

| Check | Result |
|---|---|
| `CODEX_HOME` | `/Users/teobun/arc-secure/codex-v4-home` |
| `codex login status` | `Logged in using ChatGPT` |
| Authentication mode | `chatgpt_subscription` |
| CLI | `codex-cli 0.133.0-alpha.1` |
| Config SHA-256 | `f94270078be62298be8a9ed92fb13fcb0a5480521943493df59108e5370bce10` |
| Provider | `codex` |
| Model | `gpt-5.5` |
| Reasoning | `high` |
| Provider timeout | `600` seconds |
| Config/home stability | verified before qualification and unchanged afterward |
| Provider qualification | one disposable non-benchmark probe passed |
| Benchmark provider execution | `false` |
| V6 freeze | not run |
| V6/a001 | not created |

The probe evidence is stored outside benchmark result directories. It records
only sanitized lifecycle metadata and non-secret provider identity; it is not
scientific evidence.
