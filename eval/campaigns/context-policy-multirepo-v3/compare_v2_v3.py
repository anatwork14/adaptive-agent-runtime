"""Prove that V3 changes apparatus only relative to the frozen V2 design."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ORDER = ("click", "httpx", "python-dotenv")
BASELINES = ("b3", "b5", "b7")
NORMALIZATION = [
    "campaign_id",
    "parent_campaign metadata",
    "study_id",
    "benchmark_id",
    "apparatus qualification metadata",
    "ARC commit",
]
PROTOCOL_KEYS = (
    "context_token_budget",
    "hard_task_usd",
    "hard_project_usd",
    "repeats",
    "bootstrap_samples",
    "ci",
    "meta_bootstrap_samples",
    "meta_ci",
    "meta_random_seed",
)


def _canonical(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return payload


def _normalize(value: Any, *, root: bool = True) -> Any:
    """Remove only identifiers and apparatus metadata listed by the contract."""
    if isinstance(value, list):
        return [_normalize(item, root=False) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"campaign_id", "study_id", "benchmark_id", "arc_commit"}:
            continue
        if root and key == "parent_campaign":
            continue
        if key in {"apparatus_qualification", "freeze_gate"}:
            continue
        # The runtime version policy documents which campaign is being
        # prepared; it is apparatus metadata, not a scientific parameter.
        if key == "version_policy":
            continue
        result[key] = _normalize(item, root=False)
    return result


def _manifest(campaign_dir: Path, slug: str, baseline: str) -> dict[str, Any]:
    path = campaign_dir / slug / f"{baseline}.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"manifest is not an object: {path}")
    return payload


def _manifest_scientific_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    result.pop("benchmark_id", None)
    return result


def _repo_contracts_equal(v2: dict[str, Any], v3: dict[str, Any]) -> bool:
    return all(
        v2[slug]["commit"] == v3[slug]["commit"]
        and v2[slug]["hidden_tree_sha256"] == v3[slug]["hidden_tree_sha256"]
        for slug in REPOSITORY_ORDER
    )


def _task_manifests_equal(v2_dir: Path, v3_dir: Path) -> bool:
    return all(
        _manifest_scientific_payload(_manifest(v2_dir, slug, baseline))
        == _manifest_scientific_payload(_manifest(v3_dir, slug, baseline))
        for slug in REPOSITORY_ORDER
        for baseline in BASELINES
    )


def _protocol_checks(v2: dict[str, Any], v3: dict[str, Any]) -> bool:
    left = v2["shared_protocol"]
    right = v3["shared_protocol"]
    expected = {
        "context_token_budget": 12000,
        "hard_task_usd": 2.0,
        "hard_project_usd": 350.0,
        "repeats": 6,
        "bootstrap_samples": 2000,
        "ci": 0.95,
        "meta_bootstrap_samples": 5000,
        "meta_ci": 0.95,
        "meta_random_seed": 42,
    }
    return all(left[key] == right[key] == value for key, value in expected.items())


def compare(v2_path: Path, v3_path: Path) -> dict[str, Any]:
    v2 = _load_json(v2_path)
    v3 = _load_json(v3_path)
    v2_dir = v2_path.parent
    v3_dir = v3_path.parent
    v2_repos = v2["repositories"]
    v3_repos = v3["repositories"]
    checks = {
        "target_repository_shas": _repo_contracts_equal(v2_repos, v3_repos),
        "hidden_tree_digests": all(
            v2_repos[slug]["hidden_tree_sha256"] == v3_repos[slug]["hidden_tree_sha256"]
            for slug in REPOSITORY_ORDER
        ),
        "task_definitions_order_dependencies_acceptance": _task_manifests_equal(v2_dir, v3_dir),
        "seeds": _task_manifests_equal(v2_dir, v3_dir),
        "treatments_B3_B5_B7": v2["treatments"] == v3["treatments"],
        "protocol_budgets_repeats_bootstrap_ci_seeds": _protocol_checks(v2, v3),
        "provider_model": v2["provider_profile"]["model"]
        == v3["provider_profile"]["model"]
        == "gpt-5.5",
        "codex_command": (
            v2["provider_profile"]["command_override"] == v3["provider_profile"]["command_override"]
            and v2["provider_profile"]["effective_argv"] == v3["provider_profile"]["effective_argv"]
        ),
        "docker_harnesses": all(
            v2_repos[slug]["visible_test_harness"] == v3_repos[slug]["visible_test_harness"]
            for slug in REPOSITORY_ORDER
        ),
        "hidden_test_patterns": _task_manifests_equal(v2_dir, v3_dir),
    }
    normalized_v2 = _normalize(v2)
    normalized_v3 = _normalize(v3)
    all_checks = all(checks.values()) and normalized_v2 == normalized_v3
    return {
        "schema": "arc-v3-scientific-equivalence-v1",
        "v2_contract": str(v2_path.resolve()),
        "v3_contract": str(v3_path.resolve()),
        "scientific_change": not all_checks,
        "apparatus_change_only": all_checks,
        "normalization": NORMALIZATION,
        "checks": checks,
        "normalized_v2_sha256": _sha256(normalized_v2),
        "normalized_v3_sha256": _sha256(normalized_v3),
        "all_checks_passed": all_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.v2.resolve(), args.v3.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["all_checks_passed"]:
        raise SystemExit("V2 to V3 scientific equivalence failed")


if __name__ == "__main__":
    main()
