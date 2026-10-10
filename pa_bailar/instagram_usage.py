"""What each Instagram read costs the app's hourly quota, and when the sweep stops reading.

Meta counts the app's use over a rolling hour, as shares (0-100) of calls, CPU time and total time, in one of two
headers (instagram.usage_by_header); at 100 every call fails until the hour rolls on. What binds is "total_time",
Meta's own processing time: a read costs ~1.3% normally, and three times that on a morning Meta was slow (9 Oct 2026),
when a flat stop at 90% left 23 accounts for later. So the sweep measures each read (Meta's time, the share before
and after it in the same header) and stops before a read that would take the share past config.INSTAGRAM_USAGE_CEILING:
the share now plus the next read's expected cost, the highest of the run's last few (`ReadCosts`).
"""

import statistics
from dataclasses import dataclass, field
from typing import Literal

from . import config
from .instagram import CallReading

# Why a run stopped reading accounts: the forecast (the next read would pass the ceiling), the ceiling itself (the
# share is already there), or Meta's own rate-limit error.
StopReason = Literal["forecast", "ceiling", "meta"]


@dataclass(frozen=True)
class AccountRead:
    """One account's read: Meta's time, and the share it used in the header that reported the highest (before: the
    previous read's share in that same header; None for the run's first read or a change of header)."""

    account: str
    seconds: float
    before: int | None
    after: int | None
    header: str | None

    @property
    def cost(self) -> int | None:
        """The share this read added (negative when older calls left the rolling hour meanwhile)."""
        return self.after - self.before if self.after is not None and self.before is not None else None

    def line(self) -> str:
        """For the log: "Instagram: 4.3 s, 40→44% (+4, X-App-Usage)"."""
        if self.after is None:
            return f"Instagram: {self.seconds:.1f} s, no usage reported"
        if self.cost is None:
            return f"Instagram: {self.seconds:.1f} s, {self.after}% ({self.header})"
        return f"Instagram: {self.seconds:.1f} s, {self.before}→{self.after}% ({self.cost:+d}, {self.header})"


@dataclass
class ReadsSummary:
    """A run's reads in short, for its record (run_history.json) and the admin page: how fast Meta answered, and
    what a read cost."""

    accounts: int  # reads measured
    mean_seconds: float
    median_seconds: float
    max_seconds: float
    mean_cost: float | None  # in percent of the hourly quota, over the reads with a cost (AccountRead.cost)
    max_cost: int | None
    max_cost_account: str | None
    headers: dict[str, int] = field(default_factory=dict)  # how many reads each header reported
    expected_cost: int = 0  # the forecast of the next read's cost when the run ended


class ReadCosts:
    """The run's reads, and the forecast that stops it: before each read, `stop_reason`."""

    def __init__(
        self,
        ceiling: int = config.INSTAGRAM_USAGE_CEILING,
        first_cost: int = config.INSTAGRAM_READ_COST,
        window: int = config.INSTAGRAM_COST_WINDOW,
    ):
        self.ceiling = ceiling
        self.first_cost = first_cost
        self.window = window
        self.reads: list[AccountRead] = []
        self._latest: dict[str, int] = {}  # each header's highest share in the latest read that reported it

    def expected_cost(self) -> int:
        """The next read's cost, conservatively: the highest of the last `window` measured (at least 1), or
        `first_cost` before the run has measured one."""
        costs = [read.cost for read in self.reads if read.cost is not None][-self.window :]
        return max(1, *costs) if costs else self.first_cost

    def stop_reason(self, usage: int) -> StopReason | None:
        """Whether to stop before the next read, with the share used now: at the ceiling or above, never; below it,
        when the expected cost would take the share past it."""
        if usage >= self.ceiling:
            return "ceiling"
        if usage + self.expected_cost() > self.ceiling:
            return "forecast"
        return None

    def record(self, account: str, call: CallReading) -> AccountRead:
        """An account's read, from its call (InstagramClient.last_call)."""
        header = call.header
        before = self._latest.get(header) if header else None
        read = AccountRead(account, round(call.seconds, 2), before, call.percent, header)
        for name, detail in call.usage.items():
            self._latest[name] = max(detail.values())
        self.reads.append(read)
        return read

    def summary(self) -> ReadsSummary | None:
        """The run's reads in short; None when it measured none."""
        if not self.reads:
            return None
        seconds = [read.seconds for read in self.reads]
        costed = [read for read in self.reads if read.cost is not None]
        priciest = max(costed, key=lambda read: read.cost or 0, default=None)
        headers: dict[str, int] = {}
        for read in self.reads:
            if read.header:
                headers[read.header] = headers.get(read.header, 0) + 1
        return ReadsSummary(
            accounts=len(self.reads),
            mean_seconds=round(statistics.mean(seconds), 2),
            median_seconds=round(statistics.median(seconds), 2),
            max_seconds=round(max(seconds), 2),
            mean_cost=round(statistics.mean(read.cost or 0 for read in costed), 2) if costed else None,
            max_cost=priciest.cost if priciest else None,
            max_cost_account=priciest.account if priciest else None,
            headers=headers,
            expected_cost=self.expected_cost(),
        )
