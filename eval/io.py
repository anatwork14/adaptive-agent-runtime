"""Stable file formats for ARC benchmark manifests and result records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import yaml

from eval.models import BenchmarkManifest, EvaluationSummary, TaskMeasurement


def load_manifest(path: str | Path) -> BenchmarkManifest:
    """Load and validate a JSON or YAML benchmark manifest."""
    manifest_path = Path(path)
    text = manifest_path.read_text(encoding="utf-8")
    suffix = manifest_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        raise ValueError("benchmark manifest must use .json, .yaml, or .yml")
    if not isinstance(payload, dict):
        raise ValueError("benchmark manifest root must be an object")
    return BenchmarkManifest.model_validate(payload)


def write_measurements_jsonl(
    path: str | Path,
    measurements: Iterable[TaskMeasurement],
) -> Path:
    """Write one canonical JSON object per task for append/audit-friendly results."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for measurement in measurements:
            handle.write(
                json.dumps(
                    measurement.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    return target


def read_measurements_jsonl(path: str | Path) -> list[TaskMeasurement]:
    """Read and validate task measurements; blank lines are ignored."""
    items: list[TaskMeasurement] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            items.append(TaskMeasurement.model_validate(payload))
        except Exception as exc:
            raise ValueError(f"invalid measurement JSONL at line {line_number}: {exc}") from exc
    return items


def write_summary_json(path: str | Path, summary: EvaluationSummary) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
