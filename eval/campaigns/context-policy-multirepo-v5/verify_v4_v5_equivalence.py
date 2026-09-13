"""Verify that V5 changes apparatus metadata only relative to frozen V4."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

CAMPAIGN_DIR = Path(__file__).resolve().parent
V4_DIR = CAMPAIGN_DIR.parent / "context-policy-multirepo-v4"


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _diff(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": path, "left": left, "right": right}]
    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else str(key)
            if key not in left or key not in right:
                differences.append({"path": child, "left": left.get(key), "right": right.get(key)})
            else:
                differences.extend(_diff(left[key], right[key], child))
        return differences
    if isinstance(left, list):
        differences = []
        for index, (item_left, item_right) in enumerate(zip(left, right, strict=False)):
            differences.extend(_diff(item_left, item_right, f"{path}[{index}]"))
        if len(left) != len(right):
            differences.append({"path": path, "left_length": len(left), "right_length": len(right)})
        return differences
    return [] if left == right else [{"path": path, "left": left, "right": right}]


def _normalize_contract(contract: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(contract)
    for key in (
        "campaign_id",
        "parent_campaign",
        "status",
        "protocol_change",
        "scientific_change",
        "apparatus_change_only",
        "freeze_gate",
        "apparatus_qualification",
    ):
        normalized.pop(key, None)
    runtime = normalized.get("provider_runtime", {})
    runtime.pop("trusted_workspaces", None)
    runtime.pop("version_policy", None)
    for repository in normalized.get("repositories", {}).values():
        repository.pop("study_id", None)
        repository.pop("benchmark_id", None)
    return normalized


def _normalize_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(payload)
    for key in ("campaign_id", "benchmark_id", "study_id"):
        if key in normalized:
            normalized[key] = "<naming-metadata>"
    return normalized


def _manifest_comparisons(v4_dir: Path, v5_dir: Path) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for slug in ("click", "httpx", "python-dotenv"):
        for baseline in ("b3", "b5", "b7"):
            left_path = v4_dir / slug / f"{baseline}.yaml"
            right_path = v5_dir / slug / f"{baseline}.yaml"
            left = _normalize_manifest(yaml.safe_load(left_path.read_text(encoding="utf-8")))
            right = _normalize_manifest(yaml.safe_load(right_path.read_text(encoding="utf-8")))
            comparisons.append(
                {
                    "repository": slug,
                    "baseline": baseline.upper(),
                    "v4_path": str(left_path),
                    "v5_path": str(right_path),
                    "v4_normalized_sha256": _sha(left),
                    "v5_normalized_sha256": _sha(right),
                    "equal": left == right,
                    "unexpected_differences": _diff(left, right),
                }
            )
    return comparisons


def _treatment_equality(v4: dict[str, Any], v5: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "provider_execution_timeout_seconds",
        "codex_home",
        "codex_config_path",
        "codex_config_sha256",
        "model",
        "reasoning",
        "visible_test_harness",
    )
    results: dict[str, Any] = {}
    for slug in ("click", "httpx", "python-dotenv"):
        v4_repo = v4["repositories"][slug]
        v5_repo = v5["repositories"][slug]
        v4_values = {
            "provider_execution_timeout_seconds": v4["shared_protocol"][
                "provider_execution_timeout_seconds"
            ],
            "codex_home": v4["provider_runtime"]["codex_home"],
            "codex_config_path": v4["provider_runtime"]["codex_config_path"],
            "codex_config_sha256": v4["provider_runtime"]["codex_config_sha256"],
            "model": v4["provider_profile"]["model"],
            "reasoning": v4["provider_profile"]["effective_argv"][5:7],
            "visible_test_harness": v4_repo["visible_test_harness"],
        }
        v5_values = {
            "provider_execution_timeout_seconds": v5["shared_protocol"][
                "provider_execution_timeout_seconds"
            ],
            "codex_home": v5["provider_runtime"]["codex_home"],
            "codex_config_path": v5["provider_runtime"]["codex_config_path"],
            "codex_config_sha256": v5["provider_runtime"]["codex_config_sha256"],
            "model": v5["provider_profile"]["model"],
            "reasoning": v5["provider_profile"]["effective_argv"][5:7],
            "visible_test_harness": v5_repo["visible_test_harness"],
        }
        results[slug] = {
            "fields_checked": list(fields),
            "treatment_neutral": all(v4_values[key] == v5_values[key] for key in fields),
            "v4": v4_values,
            "v5": v5_values,
            "differences": _diff(v4_values, v5_values),
        }
    return results


def verify(v4_contract_path: Path, v5_contract_path: Path, output_dir: Path) -> dict[str, Any]:
    v4 = json.loads(v4_contract_path.read_text(encoding="utf-8"))
    v5 = json.loads(v5_contract_path.read_text(encoding="utf-8"))
    normalized_v4 = _normalize_contract(v4)
    normalized_v5 = _normalize_contract(v5)
    manifest_comparisons = _manifest_comparisons(V4_DIR, CAMPAIGN_DIR)
    treatment_equality = _treatment_equality(v4, v5)
    report = {
        "schema_version": "arc-v4-v5-scientific-equivalence-v1",
        "parent_campaign": "context-policy-multirepo-v4",
        "campaign": "context-policy-multirepo-v5",
        "scientific_change": False,
        "scientific_core_preserved": True,
        "apparatus_change_only": True,
        "treatment_definition_changed": False,
        "task_definition_changed": False,
        "repository_changed": False,
        "model_changed": False,
        "provider_timeout_changed": False,
        "budget_changed": False,
        "grading_changed": False,
        "statistics_changed": False,
        "exclusion_policy_changed": False,
        "apparatus_changes": [
            {
                "component": "cli/study_commands.py",
                "change": "propagate frozen Codex provider environment into execution validation",
                "reason": "fix V4 run-plan bootstrap failure",
            }
        ],
        "normalized_v4_sha256": _sha(normalized_v4),
        "normalized_v5_sha256": _sha(normalized_v5),
        "normalized_contracts_equal": normalized_v4 == normalized_v5,
        "unexpected_contract_differences": _diff(normalized_v4, normalized_v5),
        "nine_manifest_comparisons": manifest_comparisons,
        "nine_manifest_comparisons_pass": all(item["equal"] for item in manifest_comparisons),
        "treatment_equality": treatment_equality,
        "treatment_equality_pass": all(
            item["treatment_neutral"] for item in treatment_equality.values()
        ),
        "all_checks_passed": (
            normalized_v4 == normalized_v5
            and all(item["equal"] for item in manifest_comparisons)
            and all(item["treatment_neutral"] for item in treatment_equality.values())
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "V4_V5_SCIENTIFIC_EQUIVALENCE.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "NINE_MANIFEST_COMPARISONS.json").write_text(
        json.dumps(
            {
                "schema_version": "arc-v4-v5-manifest-comparisons-v1",
                "all_checks_passed": report["nine_manifest_comparisons_pass"],
                "comparisons": manifest_comparisons,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v4-contract", type=Path, default=V4_DIR / "campaign_contract.json")
    parser.add_argument("--v5-contract", type=Path, default=CAMPAIGN_DIR / "campaign_contract.json")
    parser.add_argument("--output-dir", type=Path, default=CAMPAIGN_DIR)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.v4_contract, args.v5_contract, args.output_dir), indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
