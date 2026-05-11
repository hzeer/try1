"""Adaptive VWAP execution model tailored for Saudi Aramco (TADAWUL: 2222).

This module builds a practical schedule that:
1) Uses a 90-day intraday volume pattern as the base VWAP curve.
2) Adapts aggressiveness to current daily move and quoted spread.
3) Rebalances participation on-the-fly while honoring the parent order target.

The output is a bin-level schedule and summary metrics that can be plugged into
an execution simulator or broker API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class BinState:
    """Per-bin market state used by the adaptive allocator.

    Attributes:
        label: Human-readable bin label (e.g., "09:30-10:00").
        expected_market_volume: Forecasted market volume in this bin.
        spread_bps: Real-time average spread for the bin in basis points.
        return_from_open_bps: Price return from session open in basis points.
    """

    label: str
    expected_market_volume: float
    spread_bps: float
    return_from_open_bps: float


@dataclass(frozen=True)
class ScheduleRow:
    """Output allocation for one bin."""

    label: str
    participation_rate: float
    child_qty: float
    cumulative_qty: float


@dataclass(frozen=True)
class AdaptiveVwapConfig:
    """Risk and adaptation parameters.

    Attributes:
        min_participation: Lower cap on bin-level participation.
        max_participation: Upper cap on bin-level participation.
        spread_sensitivity: How strongly to reduce participation in wide spreads.
        trend_sensitivity: How strongly to increase/decrease participation on trend.
        chase_threshold_bps: Move threshold before trend adaptation is activated.
    """

    min_participation: float = 0.01
    max_participation: float = 0.35
    spread_sensitivity: float = 0.12
    trend_sensitivity: float = 0.08
    chase_threshold_bps: float = 35.0


def _normalize(weights: Iterable[float]) -> List[float]:
    values = [max(0.0, float(x)) for x in weights]
    total = sum(values)
    if total <= 0:
        raise ValueError("Weights must contain positive mass.")
    return [x / total for x in values]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def build_adaptive_vwap_schedule(
    parent_qty: float,
    side: str,
    bins: List[BinState],
    volume_profile_90d: List[float],
    config: AdaptiveVwapConfig = AdaptiveVwapConfig(),
) -> List[ScheduleRow]:
    """Build adaptive VWAP schedule for a single session.

    Args:
        parent_qty: Total shares to buy/sell.
        side: "buy" or "sell".
        bins: Real-time state for each intraday bin.
        volume_profile_90d: 90-day historical volume shape weights by bin.
        config: Model hyperparameters.

    Returns:
        List of ScheduleRow with bin-level participation and quantities.
    """

    if parent_qty <= 0:
        raise ValueError("parent_qty must be positive")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if len(bins) == 0:
        raise ValueError("bins must not be empty")
    if len(bins) != len(volume_profile_90d):
        raise ValueError("bins and volume_profile_90d must have equal length")

    curve = _normalize(volume_profile_90d)
    total_forecast_vol = sum(max(0.0, b.expected_market_volume) for b in bins)
    if total_forecast_vol <= 0:
        raise ValueError("expected market volume must be positive")

    target_per_bin = [parent_qty * w for w in curve]
    out: List[ScheduleRow] = []
    cumulative = 0.0

    for i, b in enumerate(bins):
        baseline_participation = target_per_bin[i] / max(b.expected_market_volume, 1e-9)

        # Spread adaptation: if spread widens, reduce aggression.
        spread_penalty = config.spread_sensitivity * b.spread_bps

        # Trend adaptation: for buy orders, positive trend encourages earlier execution;
        # for sell orders, negative trend encourages earlier execution.
        signed_move = b.return_from_open_bps if side == "buy" else -b.return_from_open_bps
        trend_boost = 0.0
        if abs(signed_move) >= config.chase_threshold_bps:
            trend_boost = config.trend_sensitivity * (signed_move / 100.0)

        adapted = baseline_participation * (1.0 - spread_penalty + trend_boost)
        participation = _clamp(adapted, config.min_participation, config.max_participation)

        child_qty = participation * max(0.0, b.expected_market_volume)

        # Keep us anchored to total parent order by redistributing any drift.
        remaining_bins = len(bins) - i
        remaining_target = parent_qty - cumulative
        child_qty = min(child_qty, remaining_target)
        if remaining_bins == 1:
            child_qty = remaining_target

        cumulative += child_qty
        out.append(
            ScheduleRow(
                label=b.label,
                participation_rate=participation,
                child_qty=child_qty,
                cumulative_qty=cumulative,
            )
        )

    return out


def example_usage() -> None:
    """Small runnable example for Saudi Aramco style session bins."""

    bins = [
        BinState("10:00-10:30", 2_300_000, 5.0, 8.0),
        BinState("10:30-11:00", 2_100_000, 5.8, 15.0),
        BinState("11:00-11:30", 1_900_000, 6.4, 28.0),
        BinState("11:30-12:00", 1_800_000, 7.1, 42.0),
        BinState("12:00-12:30", 1_700_000, 6.6, 39.0),
        BinState("12:30-13:00", 1_650_000, 6.0, 33.0),
        BinState("13:00-13:30", 1_750_000, 5.7, 30.0),
        BinState("13:30-14:00", 2_000_000, 5.2, 25.0),
        BinState("14:00-14:30", 2_350_000, 4.9, 18.0),
        BinState("14:30-15:00", 2_600_000, 4.6, 12.0),
    ]

    volume_profile_90d = [0.11, 0.10, 0.09, 0.08, 0.08, 0.08, 0.09, 0.11, 0.13, 0.13]

    schedule = build_adaptive_vwap_schedule(
        parent_qty=1_000_000,
        side="buy",
        bins=bins,
        volume_profile_90d=volume_profile_90d,
    )

    for row in schedule:
        print(
            f"{row.label} | participation={row.participation_rate:.3%} "
            f"| child_qty={row.child_qty:,.0f} | cumulative={row.cumulative_qty:,.0f}"
        )


if __name__ == "__main__":
    example_usage()
