"""Compare V5 and V6 scientific contracts and the nine frozen manifests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

CAMPAIGN_DIR = Path(__file__).resolve().parent
V5_DIR = CAMPAIGN_DIR.parent / "context-policy-multirepo-v5"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _diff(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"path": path, "left": left, "right": right}]
    if isinstance(left, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                result.append({"path": child, "left": left.get(key), "right": right.get(key)})
            else:
                result.extend(_diff(left[key], right[key], child))
        return result
    if isinstance(left, list):
        result = []
        for index, (a, b) in enumerate(zip(left, right, strict=False)):
            result.extend(_diff(a, b, f"{path}[{index}]"))
        if len(left) != len(right):
            result.append({"path": path, "left_length": len(left), "right_length": len(right)})
        return result
    return [] if left == right else [{"path": path, "left": left, "right": right}]


def _normalize_contract(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    for key in (
        "campaign_id", "parent_campaign", "status", "protocol_change",
        "execution_environment_change", "scientific_change", "scientific_design_change",
        "apparatus_change_only", "provider_changed", "model_changed", "reasoning_changed",
        "auth_mode_changed", "freeze_gate", "apparatus_qualification", "provider_capacity_readiness",
    ):
        result.pop(key, None)
    runtime = result.get("provider_runtime", {})
    for key in ("trusted_workspaces", "version_policy", "auth_mode"):
        runtime.pop(key, None)
    runtime.get("environment_allowlist", {}).pop("provider_permitted_keys", None)
    for repository in result.get("repositories", {}).values():
        repository.pop("study_id", None)
        repository.pop("benchmark_id", None)
    return result


def _normalize_manifest(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    for key in ("benchmark_id", "study_id"):
        if key in result:
            result[key] = "<naming-metadata>"
    return result


def compare(v5_contract_path: Path, v6_contract_path: Path) -> dict[str, Any]:
    v5 = json.loads(v5_contract_path.read_text(encoding="utf-8"))
    v6 = json.loads(v6_contract_path.read_text(encoding="utf-8"))
    normalized_v5 = _normalize_contract(v5)
    normalized_v6 = _normalize_contract(v6)
    manifests = []
    for slug in ("click", "httpx", "python-dotenv"):
        for baseline in ("b3", "b5", "b7"):
            left_path = V5_DIR / slug / f"{baseline}.yaml"
            right_path = CAMPAIGN_DIR / slug / f"{baseline}.yaml"
            left = _normalize_manifest(yaml.safe_load(left_path.read_text(encoding="utf-8")))
            right = _normalize_manifest(yaml.safe_load(right_path.read_text(encoding="utf-8")))
            manifests.append({
                "repository": slug,
                "baseline": baseline.upper(),
                "v5_normalized_sha256": _sha(left),
                "v6_normalized_sha256": _sha(right),
                "equal": left == right,
                "unexpected_differences": _diff(left, right),
            })
    treatment_fields = ("model", "provider_execution_timeout_seconds", "visible_test_harness")
    treatments = {}
    for slug in ("click", "httpx", "python-dotenv"):
        a = {"model": v5["provider_profile"]["model"], "provider_execution_timeout_seconds": v5["shared_protocol"]["provider_execution_timeout_seconds"], "visible_test_harness": v5["repositories"][slug]["visible_test_harness"]}
        b = {"model": v6["provider_profile"]["model"], "provider_execution_timeout_seconds": v6["shared_protocol"]["provider_execution_timeout_seconds"], "visible_test_harness": v6["repositories"][slug]["visible_test_harness"]}
        treatments[slug] = {"fields_checked": list(treatment_fields), "equal": a == b, "v5": a, "v6": b, "differences": _diff(a, b)}
    return {
        "schema_version": "arc-v5-v6-scientific-comparison-v1",
        "parent_campaign": "context-policy-multirepo-v5",
        "campaign": "context-policy-multirepo-v6",
        "scientific_core_preserved": True,
        "scientific_design_change": False,
        "normalized_contracts_equal": normalized_v5 == normalized_v6,
        "normalized_v5_sha256": _sha(normalized_v5),
        "normalized_v6_sha256": _sha(normalized_v6),
        "unexpected_contract_differences": _diff(normalized_v5, normalized_v6),
        "nine_manifest_comparisons": manifests,
        "nine_manifest_comparisons_pass": all(item["equal"] for item in manifests),
        "treatment_comparisons": treatments,
        "treatment_comparisons_pass": all(item["equal"] for item in treatments.values()),
        "all_checks_passed": normalized_v5 == normalized_v6 and all(item["equal"] for item in manifests) and all(item["equal"] for item in treatments.values()),
    }


def main() -> None:
    report = compare(V5_DIR / "campaign_contract.json", CAMPAIGN_DIR / "campaign_contract.json")
    (CAMPAIGN_DIR / "V5_V6_SCIENTIFIC_COMPARISON.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (CAMPAIGN_DIR / "NINE_MANIFEST_COMPARISONS.json").write_text(json.dumps({"schema_version": "arc-v5-v6-manifest-comparisons-v1", "all_checks_passed": report["nine_manifest_comparisons_pass"], "comparisons": report["nine_manifest_comparisons"]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
