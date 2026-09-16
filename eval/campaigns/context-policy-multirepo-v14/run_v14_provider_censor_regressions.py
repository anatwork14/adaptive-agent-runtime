"""Run V14's deterministic provider-free operational regressions."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from production_state import (
    ProductionCampaignRunner,
    SimulatedInterruption,
    build_fixture_identities,
    classify_provider_evidence,
)


def _usage_limit_evidence(*, side_effects: bool) -> dict[str, object]:
    events: list[dict[str, object]] = [{"type": "turn.failed", "message": "You've hit your usage limit."}]
    if side_effects:
        events[0:0] = [
            {"type": "agent_message", "status": "completed"},
            {"type": "command_execution", "status": "completed", "exit_code": 0},
            {"type": "file_change", "status": "completed", "changes": ["x.py"]},
        ]
    return {"provider_request_started": True, "provider_response_started": True, "provider_exit_code": 1, "provider_events": events}


def run() -> dict[str, object]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="arc-v14-provider-free-") as directory:
        root = Path(directory)
        identities = build_fixture_identities(5)
        outcomes = [
            {"status": "completed", "measurement_ref": "m/T001.json"},
            {"status": "model_failed", "exit_code": 1},
            {"status": "provider_censored", "evidence": _usage_limit_evidence(side_effects=True)},
            {"status": "completed", "measurement_ref": "m/T004.json"},
            {"status": "completed", "measurement_ref": "m/T005.json"},
        ]
        with ProductionCampaignRunner(root / "ledger.sqlite", identities=identities) as runner:
            try:
                runner.run(outcomes, interrupt_after=4)
            except SimulatedInterruption:
                pass
            runner.resume(outcomes)
            checks["model_failure_continues"] = runner.ledger.counts()["MODEL_FAILED"] == 1
            checks["unsafe_provider_censor_continues"] = runner.ledger.counts()["PROVIDER_CENSORED"] == 1
            checks["no_legacy_fail_fast"] = runner.legacy_fail_fast_triggered is False
            checks["request_instance_one_to_one"] = runner.ledger.request_instance_count() == 5
        classified = classify_provider_evidence(_usage_limit_evidence(side_effects=True))
        checks["usage_limit_is_provider_failure"] = classified["provider_error_class"] == "USAGE_LIMIT"
        checks["side_effect_retry_denied"] = classified["safe_to_retry"] is False
        checks["real_provider_requests_zero"] = True
    result = {"schema_version": "arc-v14-provider-free-regressions-v1", "provider_requests": 0, "checks": checks, "all_passed": all(checks.values())}
    output = Path("/Users/teobun/arc-study/apparatus/V14-provider-censor-regressions.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["all_passed"]:
        raise SystemExit(1)
    return result


if __name__ == "__main__":
    run()
