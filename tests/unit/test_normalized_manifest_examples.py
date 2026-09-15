"""Packaged normalized manifest templates must remain structurally comparable."""

from __future__ import annotations

from pathlib import Path

from eval.comparison import validate_comparable_manifests
from eval.io import load_manifest


def test_packaged_normalized_manifests_are_pairwise_comparable() -> None:
    root = Path(__file__).resolve().parents[2]
    examples = root / "eval" / "examples"
    b3 = load_manifest(examples / "normalized_b3.yaml")
    b5 = load_manifest(examples / "normalized_b5.yaml")
    b7 = load_manifest(examples / "normalized_b7.yaml")

    assert (b3.baseline, b5.baseline, b7.baseline) == ("B3", "B5", "B7")
    validate_comparable_manifests(b3, b5)
    validate_comparable_manifests(b5, b7)
    validate_comparable_manifests(b3, b7)
