"""Track skill usage, success rate, and execution time."""

import time
import logging
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillMetric:
    name: str
    invocations: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0
    last_used: Optional[float] = None

    @property
    def success_rate(self) -> float:
        if self.invocations == 0:
            return 0.0
        return self.successes / self.invocations * 100

    @property
    def avg_duration_ms(self) -> float:
        if self.successes == 0:
            return 0.0
        return self.total_duration_ms / self.successes


class SkillMetricsTracker:
    """In-memory skill usage metrics."""

    def __init__(self):
        self._metrics: Dict[str, SkillMetric] = defaultdict(
            lambda: SkillMetric(name="")
        )

    def record_start(self, skill_name: str) -> float:
        """Record skill invocation start. Returns start timestamp."""
        metric = self._metrics[skill_name]
        metric.name = skill_name
        metric.invocations += 1
        metric.last_used = time.time()
        return time.time()

    def record_success(self, skill_name: str, start_time: float):
        """Record successful skill execution."""
        metric = self._metrics[skill_name]
        metric.successes += 1
        metric.total_duration_ms += (time.time() - start_time) * 1000

    def record_failure(self, skill_name: str, start_time: float):
        """Record failed skill execution."""
        metric = self._metrics[skill_name]
        metric.failures += 1

    def get_metrics(self) -> list:
        """Return all metrics sorted by usage."""
        return sorted(
            [m for m in self._metrics.values() if m.invocations > 0],
            key=lambda m: m.invocations,
            reverse=True,
        )

    def get_summary(self) -> dict:
        """Return summary stats."""
        metrics = self.get_metrics()
        return {
            "total_skills_used": len(metrics),
            "total_invocations": sum(m.invocations for m in metrics),
            "overall_success_rate": (
                sum(m.successes for m in metrics)
                / max(sum(m.invocations for m in metrics), 1)
                * 100
            ),
            "most_used": metrics[0].name if metrics else None,
            "skills": [
                {
                    "name": m.name,
                    "invocations": m.invocations,
                    "success_rate": round(m.success_rate, 1),
                    "avg_duration_ms": round(m.avg_duration_ms, 1),
                }
                for m in metrics
            ],
        }
