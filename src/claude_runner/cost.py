"""Per-job cost cap."""

from __future__ import annotations

import threading

from .result import RunResult


class CostCapExceeded(RuntimeError):
    """Raised when a run is requested after the job's spend reached the cap."""

    def __init__(self, spent_usd: float, cap_usd: float) -> None:
        super().__init__(f"cost cap reached: spent ${spent_usd:.4f} of ${cap_usd:.4f}")
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd


class CostGuard:
    """Accumulates cost across the runs of one job and blocks runs at the cap.

    The cap is checked before each run, so the run that crosses it still
    completes: the overshoot is at most one run. `cap_usd <= 0` disables it.
    Thread-safe.
    """

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = float(cap_usd)
        self._spent = 0.0
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        with self._lock:
            return self._spent

    @property
    def exhausted(self) -> bool:
        return self.cap_usd > 0 and self.spent_usd >= self.cap_usd

    def check(self) -> None:
        """Raise `CostCapExceeded` if no further run is allowed."""
        spent = self.spent_usd
        if self.cap_usd > 0 and spent >= self.cap_usd:
            raise CostCapExceeded(spent, self.cap_usd)

    def record(self, result: RunResult | float) -> float:
        """Add a run's cost (a RunResult or a number); returns the total."""
        cost = result if isinstance(result, (int, float)) else result.cost_usd
        with self._lock:
            self._spent += float(cost or 0.0)
            return self._spent

    def run(self, runner, prompt: str) -> RunResult:
        """Check the cap, run once, record the cost."""
        self.check()
        result = runner.run(prompt)
        self.record(result)
        return result
