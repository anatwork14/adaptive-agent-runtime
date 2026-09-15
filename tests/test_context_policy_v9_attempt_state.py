from __future__ import annotations

import sys
from pathlib import Path

CAMPAIGN_DIR = Path(__file__).parents[1] / "eval" / "campaigns" / "context-policy-multirepo-v9"
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))

from attempt_state import AttemptStateStore, TaskIdentity, TaskState, classify_provider_censor


def _evidence(**overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "classification": "PROVIDER_CENSORED",
        "provider_error_class": "USAGE_LIMIT",
        "model_output_generated": False,
        "tool_execution_started": False,
        "repository_modified": False,
    }
    evidence.update(overrides)
    return evidence


def test_explicit_censor_classification_and_safe_retry_gate() -> None:
    assert classify_provider_censor(_evidence())["safe_to_retry"] is True
    assert classify_provider_censor(_evidence(tool_execution_started=True))["safe_to_retry"] is False


def test_atomic_checkpoint_resume_and_bounded_retry(tmp_path: Path) -> None:
    identity = TaskIdentity("click", 3, "B7", "T001")
    with AttemptStateStore(tmp_path / "state.sqlite", max_provider_censor_retries=1) as store:
        store.register([identity])
        store.start_execution(identity, "e001", model="gpt-5.5", config_identity="frozen")
        store.censor_execution(identity, "e001", _evidence())
        assert store.state(identity) == TaskState.PROVIDER_CENSORED
        assert store.campaign_score() is None
        assert store.resume_actions(provider_available=False)[identity.key] == "STOP_PROVIDER_CENSORED"
        assert store.resume_actions(provider_available=True)[identity.key] == "RETRY_PROVIDER_CENSORED"
        store.start_execution(identity, "e002", model="gpt-5.5", config_identity="frozen")
        store.complete_execution(identity, "e002", task_metric={"resolved": True})
        assert [row["instance_id"] for row in store.instances(identity)] == ["e001", "e002"]
        assert store.campaign_score()["task_count"] == 1
        try:
            store.complete_execution(identity, "e002", task_metric={"resolved": False})
        except ValueError as error:
            assert "immutable" in str(error)
        else:
            raise AssertionError("completed execution instance was mutable")


def test_provider_censor_after_mutation_cannot_retry(tmp_path: Path) -> None:
    identity = TaskIdentity("httpx", 1, "B3", "T001")
    with AttemptStateStore(tmp_path / "state.sqlite") as store:
        store.register([identity])
        store.start_execution(identity, "e001", model="gpt-5.5", config_identity="frozen")
        store.censor_execution(identity, "e001", _evidence(repository_modified=True))
        assert store.resume_actions(provider_available=True)[identity.key] == "STOP_PROVIDER_CENSORED"
        try:
            store.start_execution(identity, "e002", model="gpt-5.5", config_identity="frozen")
        except ValueError as error:
            assert "not safe" in str(error)
        else:
            raise AssertionError("unsafe provider retry was allowed")
