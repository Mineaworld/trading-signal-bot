from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from trading_signal_bot.indicators.lwma import calculate_lwma
from trading_signal_bot.indicators.stochastic import calculate_stochastic, stoch_in_zone
from trading_signal_bot.models import Direction, IndicatorParams, Scenario, Signal
from trading_signal_bot.utils import utc_now


@dataclass(frozen=True)
class M15Context:
    lwma_fast: pd.Series
    lwma_slow: pd.Series
    stoch_k: pd.Series
    stoch_d: pd.Series
    order: str
    stoch_cross_above: bool
    stoch_cross_below: bool


class StrategyEvaluator:
    def __init__(self, params: IndicatorParams) -> None:
        self._params = params

    def m15_requires_m1(
        self,
        m15_df: pd.DataFrame,
        m15_close_time_utc: datetime,
    ) -> bool:
        context = self._build_m15_context(m15_df)
        if context is None:
            return False

        idx = len(m15_df) - 1
        m15_k = float(context.stoch_k.iloc[idx])
        if np.isnan(m15_k):
            return False

        buy_pre = (
            context.order == "bullish"
            and stoch_in_zone(m15_k, self._params.buy_zone)
            and context.stoch_cross_above
        )
        sell_pre = (
            context.order == "bearish"
            and stoch_in_zone(m15_k, self._params.sell_zone)
            and context.stoch_cross_below
        )
        _ = m15_close_time_utc
        return buy_pre or sell_pre

    def evaluate(
        self,
        m15_df: pd.DataFrame,
        m1_df: pd.DataFrame,
        symbol: str,
        m15_close_time_utc: datetime,
        price: float | None = None,
    ) -> Signal | None:
        signals = self.evaluate_all(
            m15_df=m15_df,
            m1_df=m1_df,
            symbol=symbol,
            m15_close_time_utc=m15_close_time_utc,
            price=price,
        )
        if not signals:
            return None
        return signals[0]

    def evaluate_all(
        self,
        m15_df: pd.DataFrame,
        m1_df: pd.DataFrame,
        symbol: str,
        m15_close_time_utc: datetime,
        price: float | None = None,
    ) -> list[Signal]:
        context = self._build_m15_context(m15_df)
        if context is None:
            return []

        idx = len(m15_df) - 1
        m15_k = float(context.stoch_k.iloc[idx])
        m15_d = float(context.stoch_d.iloc[idx])
        m15_fast = float(context.lwma_fast.iloc[idx])
        m15_slow = float(context.lwma_slow.iloc[idx])
        if np.isnan([m15_k, m15_d, m15_fast, m15_slow]).any():
            return []

        buy_pre = (
            context.order == "bullish"
            and stoch_in_zone(m15_k, self._params.buy_zone)
            and context.stoch_cross_above
        )
        sell_pre = (
            context.order == "bearish"
            and stoch_in_zone(m15_k, self._params.sell_zone)
            and context.stoch_cross_below
        )
        if not buy_pre and not sell_pre:
            return []

        m1_ctx = self._build_m1_context(m1_df)
        if m1_ctx is None:
            return []

        m15_prev_close = m15_close_time_utc - timedelta(minutes=15)
        candidate = self._select_m1_candidate(
            m1_ctx.df,
            m15_prev_close,
            m15_close_time_utc,
        )
        if candidate is None:
            return []
        m1_pos, m1_close_time = candidate
        m1_close_price = float(m1_ctx.df.iloc[m1_pos]["close"])
        signals: list[Signal] = []

        # BUY scenarios: evaluate independently, no intra-side priority.
        if (
            context.order == "bullish"
            and stoch_in_zone(m15_k, self._params.buy_zone)
            and context.stoch_cross_above
        ):
            m1_k = float(m1_ctx.stoch_k.iloc[m1_pos])
            m1_d = float(m1_ctx.stoch_d.iloc[m1_pos])
            m1_cross_above, _ = _cross_at(m1_ctx.stoch_k, m1_ctx.stoch_d, m1_pos)
            if (
                not np.isnan([m1_k, m1_d]).any()
                and m1_cross_above
                and stoch_in_zone(m1_k, self._params.buy_zone)
            ):
                signals.append(
                    self._make_signal(
                        symbol=symbol,
                        direction=Direction.BUY,
                        scenario=Scenario.BUY_S1,
                        price=price if price is not None else m1_close_price,
                        m15_close_time_utc=m15_close_time_utc,
                        m1_close_time_utc=m1_close_time,
                        m15_fast=m15_fast,
                        m15_slow=m15_slow,
                        m15_k=m15_k,
                        m15_d=m15_d,
                        m1_k=m1_k,
                        m1_d=m1_d,
                    )
                )

            m1_fast = float(m1_ctx.lwma_fast.iloc[m1_pos])
            m1_slow = float(m1_ctx.lwma_slow.iloc[m1_pos])
            m1_lwma_cross_above, _ = _cross_at(
                m1_ctx.lwma_fast,
                m1_ctx.lwma_slow,
                m1_pos,
            )
            if not np.isnan([m1_fast, m1_slow]).any() and m1_lwma_cross_above:
                signals.append(
                    self._make_signal(
                        symbol=symbol,
                        direction=Direction.BUY,
                        scenario=Scenario.BUY_S2,
                        price=price if price is not None else m1_close_price,
                        m15_close_time_utc=m15_close_time_utc,
                        m1_close_time_utc=m1_close_time,
                        m15_fast=m15_fast,
                        m15_slow=m15_slow,
                        m15_k=m15_k,
                        m15_d=m15_d,
                        m1_fast=m1_fast,
                        m1_slow=m1_slow,
                    )
                )

        # SELL scenarios: evaluate independently, no intra-side priority.
        if (
            context.order == "bearish"
            and stoch_in_zone(m15_k, self._params.sell_zone)
            and context.stoch_cross_below
        ):
            m1_k = float(m1_ctx.stoch_k.iloc[m1_pos])
            m1_d = float(m1_ctx.stoch_d.iloc[m1_pos])
            _, m1_cross_below = _cross_at(m1_ctx.stoch_k, m1_ctx.stoch_d, m1_pos)
            if (
                not np.isnan([m1_k, m1_d]).any()
                and m1_cross_below
                and stoch_in_zone(m1_k, self._params.sell_zone)
            ):
                signals.append(
                    self._make_signal(
                        symbol=symbol,
                        direction=Direction.SELL,
                        scenario=Scenario.SELL_S1,
                        price=price if price is not None else m1_close_price,
                        m15_close_time_utc=m15_close_time_utc,
                        m1_close_time_utc=m1_close_time,
                        m15_fast=m15_fast,
                        m15_slow=m15_slow,
                        m15_k=m15_k,
                        m15_d=m15_d,
                        m1_k=m1_k,
                        m1_d=m1_d,
                    )
                )

            m1_fast = float(m1_ctx.lwma_fast.iloc[m1_pos])
            m1_slow = float(m1_ctx.lwma_slow.iloc[m1_pos])
            _, m1_lwma_cross_below = _cross_at(
                m1_ctx.lwma_fast,
                m1_ctx.lwma_slow,
                m1_pos,
            )
            if not np.isnan([m1_fast, m1_slow]).any() and m1_lwma_cross_below:
                signals.append(
                    self._make_signal(
                        symbol=symbol,
                        direction=Direction.SELL,
                        scenario=Scenario.SELL_S2,
                        price=price if price is not None else m1_close_price,
                        m15_close_time_utc=m15_close_time_utc,
                        m1_close_time_utc=m1_close_time,
                        m15_fast=m15_fast,
                        m15_slow=m15_slow,
                        m15_k=m15_k,
                        m15_d=m15_d,
                        m1_fast=m1_fast,
                        m1_slow=m1_slow,
                    )
                )

        return signals

    def evaluate_m1_only(
        self,
        m1_df: pd.DataFrame,
        symbol: str,
        price: float | None = None,
    ) -> Signal | None:
        """Evaluate M1-only strategy (no M15 confirmation required).

        BUY_M1:  M1 LWMA200 crosses above LWMA350 AND M1 Stoch %K in buy zone.
        SELL_M1: M1 LWMA200 crosses below LWMA350 AND M1 Stoch %K in sell zone.
        """
        m1_ctx = self._build_m1_context(m1_df)
        if m1_ctx is None:
            return None

        idx = len(m1_ctx.df) - 1
        m1_fast = float(m1_ctx.lwma_fast.iloc[idx])
        m1_slow = float(m1_ctx.lwma_slow.iloc[idx])
        m1_k = float(m1_ctx.stoch_k.iloc[idx])
        m1_d = float(m1_ctx.stoch_d.iloc[idx])
        if np.isnan([m1_fast, m1_slow, m1_k, m1_d]).any():
            return None

        crossed_above, crossed_below = _cross_at(
            m1_ctx.lwma_fast,
            m1_ctx.lwma_slow,
            idx,
        )

        bar_open = pd.to_datetime(m1_ctx.df.iloc[idx]["time"], utc=True)
        bar_close = bar_open + timedelta(minutes=1)
        bar_close_dt = bar_close.to_pydatetime()
        bar_close_price = float(m1_ctx.df.iloc[idx]["close"])

        if crossed_above and stoch_in_zone(m1_k, self._params.buy_zone):
            return Signal(
                id=Signal.new_id(),
                symbol=symbol,
                direction=Direction.BUY,
                scenario=Scenario.BUY_M1,
                price=price if price is not None else bar_close_price,
                created_at_utc=utc_now(),
                m1_bar_time_utc=bar_close_dt,
                m1_lwma_fast=m1_fast,
                m1_lwma_slow=m1_slow,
                m1_stoch_k=m1_k,
                m1_stoch_d=m1_d,
            )

        if crossed_below and stoch_in_zone(m1_k, self._params.sell_zone):
            return Signal(
                id=Signal.new_id(),
                symbol=symbol,
                direction=Direction.SELL,
                scenario=Scenario.SELL_M1,
                price=price if price is not None else bar_close_price,
                created_at_utc=utc_now(),
                m1_bar_time_utc=bar_close_dt,
                m1_lwma_fast=m1_fast,
                m1_lwma_slow=m1_slow,
                m1_stoch_k=m1_k,
                m1_stoch_d=m1_d,
            )

        return None

    def _make_signal(
        self,
        symbol: str,
        direction: Direction,
        scenario: Scenario,
        price: float,
        m15_close_time_utc: datetime,
        m1_close_time_utc: datetime,
        m15_fast: float,
        m15_slow: float,
        m15_k: float,
        m15_d: float,
        m1_fast: float | None = None,
        m1_slow: float | None = None,
        m1_k: float | None = None,
        m1_d: float | None = None,
    ) -> Signal:
        return Signal(
            id=Signal.new_id(),
            symbol=symbol,
            direction=direction,
            scenario=scenario,
            price=price,
            created_at_utc=utc_now(),
            m15_bar_time_utc=m15_close_time_utc.astimezone(timezone.utc),
            m1_bar_time_utc=m1_close_time_utc.astimezone(timezone.utc),
            m15_lwma_fast=m15_fast,
            m15_lwma_slow=m15_slow,
            m15_stoch_k=m15_k,
            m15_stoch_d=m15_d,
            m1_lwma_fast=m1_fast,
            m1_lwma_slow=m1_slow,
            m1_stoch_k=m1_k,
            m1_stoch_d=m1_d,
        )

    def _build_m15_context(self, m15_df: pd.DataFrame) -> M15Context | None:
        if not _has_ohlc(m15_df):
            return None
        if len(m15_df) < max(self._params.lwma_slow, self._params.stoch_k) + 2:
            return None

        close = m15_df["close"].astype(float)
        fast = calculate_lwma(close, self._params.lwma_fast)
        slow = calculate_lwma(close, self._params.lwma_slow)
        stoch_k, stoch_d = calculate_stochastic(
            close=close,
            k_period=self._params.stoch_k,
            d_period=self._params.stoch_d,
            slowing=self._params.stoch_slowing,
        )

        idx = len(m15_df) - 1
        if idx < 1:
            return None
        if np.isnan(
            [
                float(fast.iloc[idx - 1]),
                float(fast.iloc[idx]),
                float(slow.iloc[idx - 1]),
                float(slow.iloc[idx]),
                float(stoch_k.iloc[idx - 1]),
                float(stoch_k.iloc[idx]),
                float(stoch_d.iloc[idx - 1]),
                float(stoch_d.iloc[idx]),
            ]
        ).any():
            return None

        order = "bullish" if float(fast.iloc[idx]) > float(slow.iloc[idx]) else "bearish"
        if float(fast.iloc[idx]) == float(slow.iloc[idx]):
            order = "neutral"

        stoch_cross_above, stoch_cross_below = _cross_at(stoch_k, stoch_d, idx)
        return M15Context(
            lwma_fast=fast,
            lwma_slow=slow,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
            order=order,
            stoch_cross_above=stoch_cross_above,
            stoch_cross_below=stoch_cross_below,
        )

    def _build_m1_context(self, m1_df: pd.DataFrame) -> _M1Context | None:
        if not _has_ohlc(m1_df):
            return None
        if len(m1_df) < max(self._params.lwma_slow, self._params.stoch_k) + 2:
            return None

        df = m1_df.reset_index(drop=True)
        close = df["close"].astype(float)
        fast = calculate_lwma(close, self._params.lwma_fast)
        slow = calculate_lwma(close, self._params.lwma_slow)
        stoch_k, stoch_d = calculate_stochastic(
            close=close,
            k_period=self._params.stoch_k,
            d_period=self._params.stoch_d,
            slowing=self._params.stoch_slowing,
        )
        return _M1Context(
            df=df,
            lwma_fast=fast,
            lwma_slow=slow,
            stoch_k=stoch_k,
            stoch_d=stoch_d,
        )

    def _select_m1_candidate(
        self,
        m1_df: pd.DataFrame,
        m15_prev_close: datetime,
        m15_current_close: datetime,
    ) -> tuple[int, datetime] | None:
        if "time" not in m1_df.columns:
            return None
        close_times = pd.to_datetime(m1_df["time"], utc=True) + timedelta(minutes=1)
        mask = (close_times > m15_prev_close) & (close_times <= m15_current_close)
        positions = np.flatnonzero(mask.to_numpy())
        if len(positions) == 0:
            return None
        pos = int(positions[-1])
        return (pos, close_times.iloc[pos].to_pydatetime())


@dataclass(frozen=True)
class _M1Context:
    df: pd.DataFrame
    lwma_fast: pd.Series
    lwma_slow: pd.Series
    stoch_k: pd.Series
    stoch_d: pd.Series


def _cross_at(
    series_a: pd.Series,
    series_b: pd.Series,
    idx: int,
) -> tuple[bool, bool]:
    if idx < 1:
        return (False, False)
    prev_a = float(series_a.iloc[idx - 1])
    curr_a = float(series_a.iloc[idx])
    prev_b = float(series_b.iloc[idx - 1])
    curr_b = float(series_b.iloc[idx])
    if np.isnan([prev_a, curr_a, prev_b, curr_b]).any():
        return (False, False)
    crossed_above = prev_a <= prev_b and curr_a > curr_b
    crossed_below = prev_a >= prev_b and curr_a < curr_b
    return (crossed_above, crossed_below)


def _has_ohlc(df: pd.DataFrame) -> bool:
    required = {"time", "open", "high", "low", "close"}
    return required.issubset(df.columns)
