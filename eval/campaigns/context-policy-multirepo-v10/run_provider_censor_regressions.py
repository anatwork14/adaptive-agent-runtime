"""Deterministic provider-free V9 fault-handling regressions."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from attempt_state import AttemptStateStore, TaskIdentity, TaskState, classify_provider_censor


USAGE_LIMIT = {
    "classification": "PROVIDER_CENSORED",
    "provider_error_class": "USAGE_LIMIT",
    "provider_message": "You've hit your usage limit.",
    "model_output_generated": False,
    "tool_execution_started": False,
    "repository_modified": False,
}


def _complete(store: AttemptStateStore, identity: TaskIdentity, instance: str) -> None:
    store.start_execution(identity, instance, model="gpt-5.5", config_identity="frozen-v9")
    store.complete_execution(
        identity, instance, agent_terminal_state="COMPLETED", patch_commit="deadbeef",
        visible_eval={"passed": True}, hidden_eval={"passed": True},
        score_components={"resolved": 1}, artifact_hashes={"measurement": "a" * 64},
        task_metric={"resolved": True},
    )


def run() -> dict[str, object]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="arc-v9-provider-free-") as directory:
        store = AttemptStateStore(Path(directory) / "attempt.sqlite", max_provider_censor_retries=1)
        identities = [TaskIdentity("click", 3, "B7", f"T{i:03d}") for i in range(1, 20)]
        store.register(identities)
        for index, identity in enumerate(identities[:18], 1):
            _complete(store, identity, f"e{index:03d}")
        failed = identities[18]
        store.start_execution(failed, "e019", model="gpt-5.5", config_identity="frozen-v9")
        store.censor_execution(failed, "e019", USAGE_LIMIT)
        checks["18_complete_19_censored"] = all(store.state(item) == TaskState.COMPLETED for item in identities[:18]) and store.state(failed) == TaskState.PROVIDER_CENSORED
        checks["no_premature_score"] = store.campaign_score() is None
        checks["no_automatic_retry"] = store.resume_actions(provider_available=False)[failed.key] == "STOP_PROVIDER_CENSORED"
        checks["resume_waits_for_availability"] = store.resume_actions(provider_available=True)[failed.key] == "RETRY_PROVIDER_CENSORED"

        store.start_execution(failed, "e020", model="gpt-5.5", config_identity="frozen-v9")
        store.complete_execution(failed, "e020", agent_terminal_state="COMPLETED", patch_commit="cafebabe", task_metric={"resolved": True})
        history = store.instances(failed)
        checks["retry_preserves_both_instances"] = [row["instance_id"] for row in history] == ["e019", "e020"] and history[0]["state"] == TaskState.PROVIDER_CENSORED.value and history[1]["state"] == TaskState.COMPLETED.value
        checks["final_score_after_complete_set"] = store.campaign_score() is not None
        try:
            store.complete_execution(failed, "e020", task_metric={"resolved": False})
        except ValueError:
            checks["completed_immutable"] = True

        unsafe = TaskIdentity("click", 3, "B7", "T020")
        store.register([unsafe])
        store.start_execution(unsafe, "e021", model="gpt-5.5", config_identity="frozen-v9")
        unsafe_evidence = {**USAGE_LIMIT, "tool_execution_started": True}
        classified = classify_provider_censor(unsafe_evidence)
        store.censor_execution(unsafe, "e021", unsafe_evidence)
        checks["unsafe_retry_denied"] = classified["safe_to_retry"] is False and store.resume_actions(provider_available=True)[unsafe.key] == "STOP_PROVIDER_CENSORED"
        try:
            store.start_execution(unsafe, "e022", model="gpt-5.5", config_identity="frozen-v9")
        except ValueError:
            checks["unsafe_start_denied"] = True
        store.close()

    result = {"schema_version": "arc-v10-provider-censor-regressions-v1", "provider_requests": 0, "checks": checks, "all_passed": all(checks.values())}
    output = Path("/Users/teobun/arc-study/apparatus/v10-provider-censor-regressions.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["all_passed"]:
        raise SystemExit(1)
    return result


if __name__ == "__main__":
    run()
