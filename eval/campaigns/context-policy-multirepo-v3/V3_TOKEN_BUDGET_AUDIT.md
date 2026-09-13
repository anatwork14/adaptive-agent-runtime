# V3 Token-Budget Audit

## Finding

The frozen ARC experiment defines `12,000` as a matched hard *compiled-context*
ceiling. It is not a per-model-call ceiling and it is not a total provider-token
budget. The context compiler enforces the ceiling on the immutable
`ContextPacket`; provider token usage is a separately observed measurement when
the provider reports it.

The V2 implementation passes the task's matched `token_budget` value into
`AgentBudget.max_tokens`, but the real subprocess adapter uses that object only
for its wall-clock timeout. It does not pass a provider output-token option and
does not reject a completed provider turn because its reported input plus output
tokens exceed 12,000. `BudgetAccountant` enforces the frozen USD ceilings and
records token telemetry; it does not enforce a provider-token ceiling.

This is not a scientific-budget drift: the already-defined protocol is a hard
context ceiling, and the compiler correctly enforces that protocol. The
apparatus candidate therefore does not change `12,000`, `$2/task`, `$350`
project, or the measurement definition. A future protocol that intends a hard
provider-token ceiling must define it as a separate preregistered quantity and
add provider-specific enforcement before freeze.

## Questions answered

| Question | Evidence-backed answer |
|---|---|
| Is `input_tokens` cumulative across the entire Codex task? | In the captured `codex exec --json` telemetry, it is the aggregate usage reported by the emitted completion event. The Codex CLI issue tracker documents that `turn.completed` usage is cumulative session usage for this mode; the CLI does not expose a per-request “last” value in the same way as the interactive client. The exact provider-internal API-call count is not observable from this JSONL alone. |
| Does it include repeated context across model/tool turns? | Yes, the reported input total accounts for the provider's input-token accounting across the turn/session aggregate, including repeated material when the provider sends it again. The CLI output does not expose a separate per-call breakdown. |
| Are `cached_input_tokens` a subset of `input_tokens`? | Yes. It is a breakdown of input tokens, not an additional quantity to add to input tokens. |
| Are `reasoning_output_tokens` a subset of `output_tokens`? | Yes. It is a breakdown of output tokens, not an additional quantity to add to output tokens. |
| What does `AgentBudget.max_tokens` currently enforce? | For the real subprocess adapter, nothing about provider token count. It is carried through the adapter API but is not translated into a provider command limit or post-turn rejection. The context compiler's separate hard budget is enforced. |
| What is `12,000`? | The matched hard compiled-context ceiling recorded as `context_token_budget` and copied into each task's matched `token_budget`. |
| Does ARC stop a run when total provider usage exceeds 12,000? | No. There is no frozen total-provider-token rule, and the current provider adapter does not enforce one. Observed provider tokens remain a nullable research measurement. |

## V2 telemetry interpretation

The preserved V2 T001 telemetry was approximately:

```text
compiled context tokens       6,167
input_tokens                483,654
cached_input_tokens         430,208
output_tokens                 4,539
reasoning_output_tokens         708
```

ARC's provider-token measurement is:

```text
provider_tokens = input_tokens + output_tokens
               = 488,193
```

Cached input and reasoning output are retained as annotations. They are not
added a second time, so the measured total does not double-count either
breakdown. The large provider total does not imply that the compiled context
ceiling was violated.

## Code-path evidence

1. `ContextRequest.token_budget` is supplied to the compiler, which rejects a
   packet whose compiled token count exceeds that hard budget.
2. `Orchestrator.execute_task` constructs `AgentBudget(max_tokens=task.token_budget)`.
3. `SubprocessCodingAgent.run_prompt` reads `budget.timeout_seconds` for process
   supervision; no provider token flag or total-token check is present.
4. `CodexAgentAdapter` maps `input_tokens` to `prompt_tokens`,
   `output_tokens` to `completion_tokens`, and preserves cached/reasoning
   breakdowns as annotations.
5. ARC's measured provider total is `prompt_tokens + completion_tokens`.

## Primary sources

- OpenAI Codex event types and usage fields:
  <https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts>
- OpenAI Codex issue documenting cumulative `codex exec` usage semantics:
  <https://github.com/openai/codex/issues/17539>
- OpenAI Responses API usage definitions and output-token accounting:
  <https://developers.openai.com/api/reference/cli/resources/responses/methods/create>

