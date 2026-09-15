"""Statistical analysis utilities: Bootstrap confidence intervals and paired comparisons."""

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class BootstrapResult:
    mean: float
    median: float
    ci_lower: float
    ci_upper: float


class StatisticalAnalyzer:
    """Computes bootstrap confidence intervals and paired statistical comparisons."""

    @staticmethod
    def bootstrap_ci(
        values: List[float],
        n_bootstraps: int = 1000,
        ci: float = 0.95,
        random_seed: int = 42,
    ) -> BootstrapResult:
        """Compute bootstrap confidence interval for mean and median."""
        if not values:
            return BootstrapResult(mean=0.0, median=0.0, ci_lower=0.0, ci_upper=0.0)

        rng = np.random.default_rng(random_seed)
        data = np.asarray(values, dtype=np.float64)
        n = len(data)

        bootstrap_means = np.empty(n_bootstraps)
        for i in range(n_bootstraps):
            sample = rng.choice(data, size=n, replace=True)
            bootstrap_means[i] = np.mean(sample)

        alpha = (1.0 - ci) / 2.0
        lower = float(np.percentile(bootstrap_means, alpha * 100))
        upper = float(np.percentile(bootstrap_means, (1.0 - alpha) * 100))

        return BootstrapResult(
            mean=float(np.mean(data)),
            median=float(np.median(data)),
            ci_lower=round(lower, 4),
            ci_upper=round(upper, 4),
        )

    @staticmethod
    def paired_difference(
        treatment: List[float],
        control: List[float],
        n_bootstraps: int = 1000,
    ) -> BootstrapResult:
        """Compute bootstrap CI for paired difference (treatment - control)."""
        diffs = [t - c for t, c in zip(treatment, control, strict=True)]
        return StatisticalAnalyzer.bootstrap_ci(diffs, n_bootstraps=n_bootstraps)
