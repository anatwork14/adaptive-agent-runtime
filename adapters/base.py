"""Agent Adapter interface, run results, and provider diagnostics."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from context.compiler import ContextPacket
from runtime.environment import redact_command, redact_text_secrets

PROVIDER_FAILURE_CLASSIFICATIONS = (
    "CLI_NOT_FOUND",
    "CLI_NONZERO_EXIT",
    "CLI_TIMEOUT",
    "CLI_CANCELLED",
    "AUTH_FAILURE",
    "PROVIDER_SERVICE_ERROR",
    "NETWORK_ERROR",
    "CONFIGURATION_ERROR",
    "UNKNOWN_PROVIDER_FAILURE",
)

_SENSITIVE_DIAGNOSTIC_KEYS = (
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "credential",
    "authorization",
    "cookie",
    "private_key",
)
_SAFE_TOKEN_KEYS = {"token_usage", "environment_keys", "provider_tokens"}
_SUMMARY_TAIL_LIMIT = 8000
_STDOUT_TAIL_LIMIT = 8000
_STDERR_TAIL_LIMIT = 4000


def classify_provider_failure(
    *,
    status: str,
    outcome: str | None = None,
    returncode: int | None = None,
    summary: str = "",
    stdout_tail: str = "",
    stderr_tail: str = "",
) -> str:
    """Classify a provider failure without claiming more than the evidence supports."""
    if status == "cancelled" or outcome == "cancelled":
        return "CLI_CANCELLED"
    if outcome == "timeout":
        return "CLI_TIMEOUT"
    if outcome == "not_found":
        return "CLI_NOT_FOUND"

    text = " ".join((summary, stdout_tail, stderr_tail)).lower()
    if any(
        marker in text
        for marker in (
            "not authenticated",
            "authentication required",
            "auth required",
            "unauthorized",
            "invalid api key",
            "401",
            "403",
            "login required",
        )
    ):
        return "AUTH_FAILURE"
    if any(
        marker in text
        for marker in (
            "connection refused",
            "connection reset",
            "name or service not known",
            "temporary failure in name resolution",
            "dns",
            "network is unreachable",
            "broken pipe",
        )
    ):
        return "NETWORK_ERROR"
    if any(
        marker in text
        for marker in (
            "rate limit",
            "too many requests",
            "service unavailable",
            "internal server error",
            "bad gateway",
            "gateway timeout",
            "server error",
            "http 5",
            "http status 5",
            "429",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return "PROVIDER_SERVICE_ERROR"
    if any(
        marker in text
        for marker in (
            "unknown option",
            "unexpected argument",
            "invalid argument",
            "unsupported model",
            "model not found",
            "invalid configuration",
            "malformed config",
            "configuration error",
        )
    ):
        return "CONFIGURATION_ERROR"
    if returncode is not None:
        return "CLI_NONZERO_EXIT"
    return "UNKNOWN_PROVIDER_FAILURE"


def _sanitize_diagnostic_value(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if lowered in _SAFE_TOKEN_KEYS:
        if isinstance(value, dict):
            return {str(k): int(v) for k, v in value.items() if isinstance(v, (int, float))}
        if isinstance(value, list):
            return [str(item) for item in value]
        return value
    if any(marker in lowered for marker in _SENSITIVE_DIAGNOSTIC_KEYS):
        return "<redacted>"
    if lowered in {"command", "argv", "args"} and isinstance(value, list):
        return redact_command(value)
    if isinstance(value, dict):
        return {str(k): _sanitize_diagnostic_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_diagnostic_value(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_text_secrets(value)
    return value


def sanitize_failure_diagnostics(result: "AgentRunResult") -> Dict[str, Any]:
    """Return the bounded, secret-safe subset suitable for durable events."""
    returncode = result.provider_returncode
    if returncode is None:
        for trace_item in result.tool_trace:
            if isinstance(trace_item, dict) and isinstance(trace_item.get("returncode"), int):
                returncode = trace_item["returncode"]
                break
    classification = result.failure_classification
    if result.status != "completed" and not classification:
        classification = classify_provider_failure(
            status=result.status,
            outcome=result.provider_outcome,
            returncode=returncode,
            summary=result.summary,
            stdout_tail=result.stdout_tail,
            stderr_tail=result.stderr_tail,
        )
    payload: Dict[str, Any] = {
        "reason": f"agent_status={result.status}",
        "agent_status": result.status,
        "agent_summary": redact_text_secrets(result.summary)[-_SUMMARY_TAIL_LIMIT:],
        "tool_trace": result.tool_trace,
        "token_usage": result.token_usage,
        "cost_usd": result.cost_usd,
        "failure_classification": classification,
        "provider_returncode": returncode,
        "provider_outcome": result.provider_outcome,
        "stdout_tail": redact_text_secrets(result.stdout_tail)[-_STDOUT_TAIL_LIMIT:],
        "stderr_tail": redact_text_secrets(result.stderr_tail)[-_STDERR_TAIL_LIMIT:],
        "provider_lifecycle": result.provider_lifecycle,
        "provider_events": result.provider_events,
    }
    return _sanitize_diagnostic_value(payload)


class AgentBudget(BaseModel):
    max_usd: float = 5.0
    max_tokens: int = 24000
    timeout_seconds: int = 180


class AgentRunResult(BaseModel):
    status: str = "completed"  # completed | failed | cancelled | budget_exhausted
    patch_ref: str = ""
    diff: str = ""
    summary: str = ""
    memory_references: List[str] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)
    token_usage: Dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    failure_classification: Optional[str] = None
    provider_returncode: Optional[int] = None
    provider_outcome: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    provider_lifecycle: Dict[str, str] = Field(default_factory=dict)
    provider_events: List[Dict[str, Any]] = Field(default_factory=list)


class AgentAdapter(Protocol):
    """Protocol for model and CLI agent adapters."""

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult: ...
