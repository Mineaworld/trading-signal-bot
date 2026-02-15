from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from trading_signal_bot.indicators.lwma import calculate_lwma
from trading_signal_bot.indicators.stochastic import calculate_stochastic, stoch_in_zone
from trading_signal_bot.indicators.volatility import calculate_adx, calculate_atr
from trading_signal_bot.models import (
    Direction,
    IndicatorParams,
    PendingSetup,
    PendingState,
    Scenario,
    Signal,
    TriggerMode,
)
from trading_signal_bot.settings import RegimeFilterConfig, RiskContextConfig
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


@dataclass(frozen=True)
class M15Trigger:
    direction: Direction
    mode: TriggerMode
    m15_close_time_utc: datetime
    m15_lwma_fast: float
    m15_lwma_slow: float
    m15_stoch_k: float
    m15_stoch_d: float


@dataclass(frozen=True)
class M1Snapshot:
    bar_time_utc: datetime
    close_price: float
    lwma_fast: float
    lwma_slow: float
    stoch_k: float
    stoch_d: float
    lwma_cross_above: bool
    lwma_cross_below: bool
    stoch_cross_above: bool
    stoch_cross_below: bool
    stoch_in_buy_zone: bool
    stoch_in_sell_zone: bool


class StrategyEvaluator:
    def __init__(
        self,
        params: IndicatorParams,
        require_opposite_zone_on_lwma_cross: bool = True,
        regime_filter: RegimeFilterConfig | None = None,
        risk_context: RiskContextConfig | None = None,
    ) -> None:
        self._params = params
        self._require_opposite_zone_on_lwma_cross = require_opposite_zone_on_lwma_cross
        self._regime_filter = regime_filter
        self._risk_context = risk_context

    def m15_requires_m1(
        self,
        m15_df: pd.DataFrame,
        m15_close_time_utc: datetime,
    ) -> bool:
        _ = m15_close_time_utc
        return len(self.evaluate_m15_triggers(m15_df, m15_close_time_utc)) > 0

    def evaluate_m15_triggers(
        self,
        m15_df: pd.DataFrame,
        m15_close_time_utc: datetime,
    ) -> list[M15Trigger]:
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

        m15_lwma_cross_above, m15_lwma_cross_below = _cross_at(
            context.lwma_fast,
            context.lwma_slow,
            idx,
        )
        normal_buy = (
            context.order == "bullish"
            and stoch_in_zone(m15_k, self._params.buy_zone)
            and context.stoch_cross_above
        )
        normal_sell = (
            context.order == "bearish"
            and stoch_in_zone(m15_k, self._params.sell_zone)
            and context.stoch_cross_below
        )
        hp_buy = normal_buy and m15_lwma_cross_above
        hp_sell = normal_sell and m15_lwma_cross_below
        if (normal_buy or normal_sell or hp_buy or hp_sell) and not self._passes_regime_filter(m15_df):
            return []

        triggers: list[M15Trigger] = []
        if normal_buy:
            triggers.append(
                M15Trigger(
                    direction=Direction.BUY,
                    mode=TriggerMode.NORMAL,
                    m15_close_time_utc=m15_close_time_utc.astimezone(timezone.utc),
                    m15_lwma_fast=m15_fast,
                    m15_lwma_slow=m15_slow,
                    m15_stoch_k=m15_k,
                    m15_stoch_d=m15_d,
                )
            )
        if normal_sell:
            triggers.append(
                M15Trigger(
                    direction=Direction.SELL,
                    mode=TriggerMode.NORMAL,
                    m15_close_time_utc=m15_close_time_utc.astimezone(timezone.utc),
                    m15_lwma_fast=m15_fast,
                    m15_lwma_slow=m15_slow,
                    m15_stoch_k=m15_k,
                    m15_stoch_d=m15_d,
                )
            )
        if hp_buy:
            triggers.append(
                M15Trigger(
                    direction=Direction.BUY,
                    mode=TriggerMode.HIGH_PROBABILITY,
                    m15_close_time_utc=m15_close_time_utc.astimezone(timezone.utc),
                    m15_lwma_fast=m15_fast,
                    m15_lwma_slow=m15_slow,
                    m15_stoch_k=m15_k,
                    m15_stoch_d=m15_d,
                )
            )
        if hp_sell:
            triggers.append(
                M15Trigger(
                    direction=Direction.SELL,
                    mode=TriggerMode.HIGH_PROBABILITY,
                    m15_close_time_utc=m15_close_time_utc.astimezone(timezone.utc),
                    m15_lwma_fast=m15_fast,
                    m15_lwma_slow=m15_slow,
                    m15_stoch_k=m15_k,
                    m15_stoch_d=m15_d,
                )
            )
        return triggers

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
        if not self._passes_regime_filter(m15_df):
            return []

        m1_ctx = self._build_m1_context(m1_df)
        if m1_ctx is None:
            return []

        m15_prev_close = m15_close_time_utc - timedelta(minutes=15)
        candidate_positions = self._select_m1_candidates(
            m1_ctx.df,
            m15_prev_close,
            m15_close_time_utc,
        )
        if not candidate_positions:
            return []
        close_times = pd.to_datetime(m1_ctx.df["time"], utc=True) + timedelta(minutes=1)
        signals: list[Signal] = []

        if buy_pre:
            first_s1_pos: int | None = None
            first_s2_pos: int | None = None
            for pos in candidate_positions:
                m1_k = float(m1_ctx.stoch_k.iloc[pos])
                m1_d = float(m1_ctx.stoch_d.iloc[pos])
                m1_fast = float(m1_ctx.lwma_fast.iloc[pos])
                m1_slow = float(m1_ctx.lwma_slow.iloc[pos])
                if np.isnan([m1_k, m1_d, m1_fast, m1_slow]).any():
                    continue
                m1_cross_above, _ = _cross_at(m1_ctx.stoch_k, m1_ctx.stoch_d, pos)
                m1_lwma_cross_above, _ = _cross_at(m1_ctx.lwma_fast, m1_ctx.lwma_slow, pos)
                if first_s1_pos is None and m1_cross_above and stoch_in_zone(m1_k, self._params.buy_zone):
                    first_s1_pos = pos
                if first_s2_pos is None and m1_lwma_cross_above:
                    first_s2_pos = pos
                if first_s1_pos is not None and first_s2_pos is not None:
                    break

            if first_s1_pos is not None:
                m1_k = float(m1_ctx.stoch_k.iloc[first_s1_pos])
                m1_d = float(m1_ctx.stoch_d.iloc[first_s1_pos])
                m1_close_time = close_times.iloc[first_s1_pos].to_pydatetime()
                m1_close_price = float(m1_ctx.df.iloc[first_s1_pos]["close"])
                risk = self._build_risk_context(
                    m15_df=m15_df,
                    direction=Direction.BUY,
                    entry_price=price if price is not None else m1_close_price,
                    m15_fast=m15_fast,
                )
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
                        risk=risk,
                    )
                )

            if first_s2_pos is not None:
                m1_fast = float(m1_ctx.lwma_fast.iloc[first_s2_pos])
                m1_slow = float(m1_ctx.lwma_slow.iloc[first_s2_pos])
                m1_close_time = close_times.iloc[first_s2_pos].to_pydatetime()
                m1_close_price = float(m1_ctx.df.iloc[first_s2_pos]["close"])
                risk = self._build_risk_context(
                    m15_df=m15_df,
                    direction=Direction.BUY,
                    entry_price=price if price is not None else m1_close_price,
                    m15_fast=m15_fast,
                )
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
                        risk=risk,
                    )
                )

        if sell_pre:
            first_s1_pos = None
            first_s2_pos = None
            for pos in candidate_positions:
                m1_k = float(m1_ctx.stoch_k.iloc[pos])
                m1_d = float(m1_ctx.stoch_d.iloc[pos])
                m1_fast = float(m1_ctx.lwma_fast.iloc[pos])
                m1_slow = float(m1_ctx.lwma_slow.iloc[pos])
                if np.isnan([m1_k, m1_d, m1_fast, m1_slow]).any():
                    continue
                _, m1_cross_below = _cross_at(m1_ctx.stoch_k, m1_ctx.stoch_d, pos)
                _, m1_lwma_cross_below = _cross_at(m1_ctx.lwma_fast, m1_ctx.lwma_slow, pos)
                if first_s1_pos is None and m1_cross_below and stoch_in_zone(m1_k, self._params.sell_zone):
                    first_s1_pos = pos
                if first_s2_pos is None and m1_lwma_cross_below:
                    first_s2_pos = pos
                if first_s1_pos is not None and first_s2_pos is not None:
                    break

            if first_s1_pos is not None:
                m1_k = float(m1_ctx.stoch_k.iloc[first_s1_pos])
                m1_d = float(m1_ctx.stoch_d.iloc[first_s1_pos])
                m1_close_time = close_times.iloc[first_s1_pos].to_pydatetime()
                m1_close_price = float(m1_ctx.df.iloc[first_s1_pos]["close"])
                risk = self._build_risk_context(
                    m15_df=m15_df,
                    direction=Direction.SELL,
                    entry_price=price if price is not None else m1_close_price,
                    m15_fast=m15_fast,
                )
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
                        risk=risk,
                    )
                )

            if first_s2_pos is not None:
                m1_fast = float(m1_ctx.lwma_fast.iloc[first_s2_pos])
                m1_slow = float(m1_ctx.lwma_slow.iloc[first_s2_pos])
                m1_close_time = close_times.iloc[first_s2_pos].to_pydatetime()
                m1_close_price = float(m1_ctx.df.iloc[first_s2_pos]["close"])
                risk = self._build_risk_context(
                    m15_df=m15_df,
                    direction=Direction.SELL,
                    entry_price=price if price is not None else m1_close_price,
                    m15_fast=m15_fast,
                )
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
                        risk=risk,
                    )
                )

        return signals

    def evaluate_m1_only(
        self,
        m1_df: pd.DataFrame,
        symbol: str,
        price: float | None = None,
    ) -> Signal | None:
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

        crossed_above, crossed_below = _cross_at(m1_ctx.lwma_fast, m1_ctx.lwma_slow, idx)

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

    def latest_m1_snapshot(self, m1_df: pd.DataFrame) -> M1Snapshot | None:
        m1_ctx = self._build_m1_context(m1_df)
        if m1_ctx is None:
            return None

        idx = len(m1_ctx.df) - 1
        if idx < 1:
            return None

        m1_fast = float(m1_ctx.lwma_fast.iloc[idx])
        m1_slow = float(m1_ctx.lwma_slow.iloc[idx])
        m1_k = float(m1_ctx.stoch_k.iloc[idx])
        m1_d = float(m1_ctx.stoch_d.iloc[idx])
        if np.isnan([m1_fast, m1_slow, m1_k, m1_d]).any():
            return None

        lwma_cross_above, lwma_cross_below = _cross_at(m1_ctx.lwma_fast, m1_ctx.lwma_slow, idx)
        stoch_cross_above, stoch_cross_below = _cross_at(m1_ctx.stoch_k, m1_ctx.stoch_d, idx)

        bar_open = pd.to_datetime(m1_ctx.df.iloc[idx]["time"], utc=True)
        bar_close = (bar_open + timedelta(minutes=1)).to_pydatetime()
        close_price = float(m1_ctx.df.iloc[idx]["close"])

        return M1Snapshot(
            bar_time_utc=bar_close.astimezone(timezone.utc),
            close_price=close_price,
            lwma_fast=m1_fast,
            lwma_slow=m1_slow,
            stoch_k=m1_k,
            stoch_d=m1_d,
            lwma_cross_above=lwma_cross_above,
            lwma_cross_below=lwma_cross_below,
            stoch_cross_above=stoch_cross_above,
            stoch_cross_below=stoch_cross_below,
            stoch_in_buy_zone=stoch_in_zone(m1_k, self._params.buy_zone),
            stoch_in_sell_zone=stoch_in_zone(m1_k, self._params.sell_zone),
        )

    def advance_pending_setup(
        self,
        pending: PendingSetup,
        snapshot: M1Snapshot,
        price: float | None = None,
    ) -> tuple[PendingSetup | None, Signal | None]:
        if pending.direction is Direction.BUY:
            return self._advance_buy_pending(pending, snapshot, price)
        return self._advance_sell_pending(pending, snapshot, price)

    def _advance_buy_pending(
        self,
        pending: PendingSetup,
        snapshot: M1Snapshot,
        price: float | None,
    ) -> tuple[PendingSetup | None, Signal | None]:
        if pending.state is PendingState.WAIT_M1_LWMA:
            if not snapshot.lwma_cross_above:
                return (pending, None)
            if self._require_opposite_zone_on_lwma_cross and not snapshot.stoch_in_sell_zone:
                return (pending, None)
            if snapshot.stoch_cross_above:
                return (pending, None)
            return (
                PendingSetup(
                    symbol=pending.symbol,
                    direction=pending.direction,
                    mode=pending.mode,
                    state=PendingState.WAIT_M1_STOCH,
                    m15_trigger_time_utc=pending.m15_trigger_time_utc,
                    last_updated_utc=utc_now(),
                    m15_lwma_fast=pending.m15_lwma_fast,
                    m15_lwma_slow=pending.m15_lwma_slow,
                    m15_stoch_k=pending.m15_stoch_k,
                    m15_stoch_d=pending.m15_stoch_d,
                ),
                None,
            )

        if pending.state is PendingState.WAIT_M1_STOCH:
            if snapshot.stoch_cross_above and snapshot.stoch_in_buy_zone:
                return (
                    None,
                    self._make_chain_signal(
                        pending=pending,
                        snapshot=snapshot,
                        price=price if price is not None else snapshot.close_price,
                    ),
                )

        return (pending, None)

    def _advance_sell_pending(
        self,
        pending: PendingSetup,
        snapshot: M1Snapshot,
        price: float | None,
    ) -> tuple[PendingSetup | None, Signal | None]:
        if pending.state is PendingState.WAIT_M1_LWMA:
            if not snapshot.lwma_cross_below:
                return (pending, None)
            if self._require_opposite_zone_on_lwma_cross and not snapshot.stoch_in_buy_zone:
                return (pending, None)
            if snapshot.stoch_cross_below:
                return (pending, None)
            return (
                PendingSetup(
                    symbol=pending.symbol,
                    direction=pending.direction,
                    mode=pending.mode,
                    state=PendingState.WAIT_M1_STOCH,
                    m15_trigger_time_utc=pending.m15_trigger_time_utc,
                    last_updated_utc=utc_now(),
                    m15_lwma_fast=pending.m15_lwma_fast,
                    m15_lwma_slow=pending.m15_lwma_slow,
                    m15_stoch_k=pending.m15_stoch_k,
                    m15_stoch_d=pending.m15_stoch_d,
                ),
                None,
            )

        if pending.state is PendingState.WAIT_M1_STOCH:
            if snapshot.stoch_cross_below and snapshot.stoch_in_sell_zone:
                return (
                    None,
                    self._make_chain_signal(
                        pending=pending,
                        snapshot=snapshot,
                        price=price if price is not None else snapshot.close_price,
                    ),
                )

        return (pending, None)

    def _make_chain_signal(
        self,
        pending: PendingSetup,
        snapshot: M1Snapshot,
        price: float,
    ) -> Signal:
        if pending.direction is Direction.BUY:
            scenario = (
                Scenario.BUY_CHAIN_HP
                if pending.mode is TriggerMode.HIGH_PROBABILITY
                else Scenario.BUY_CHAIN
            )
        else:
            scenario = (
                Scenario.SELL_CHAIN_HP
                if pending.mode is TriggerMode.HIGH_PROBABILITY
                else Scenario.SELL_CHAIN
            )

        return Signal(
            id=Signal.new_id(),
            symbol=pending.symbol,
            direction=pending.direction,
            scenario=scenario,
            price=price,
            created_at_utc=utc_now(),
            m15_bar_time_utc=pending.m15_trigger_time_utc,
            m1_bar_time_utc=snapshot.bar_time_utc,
            m15_lwma_fast=pending.m15_lwma_fast,
            m15_lwma_slow=pending.m15_lwma_slow,
            m15_stoch_k=pending.m15_stoch_k,
            m15_stoch_d=pending.m15_stoch_d,
            m1_lwma_fast=snapshot.lwma_fast,
            m1_lwma_slow=snapshot.lwma_slow,
            m1_stoch_k=snapshot.stoch_k,
            m1_stoch_d=snapshot.stoch_d,
        )

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
        risk: tuple[float, float, float, float] | None = None,
    ) -> Signal:
        risk_stop_distance: float | None = None
        risk_invalidation_price: float | None = None
        risk_tp1_price: float | None = None
        risk_tp2_price: float | None = None
        if risk is not None:
            risk_stop_distance, risk_invalidation_price, risk_tp1_price, risk_tp2_price = risk
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
            risk_stop_distance=risk_stop_distance,
            risk_invalidation_price=risk_invalidation_price,
            risk_tp1_price=risk_tp1_price,
            risk_tp2_price=risk_tp2_price,
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

    def _select_m1_candidates(
        self,
        m1_df: pd.DataFrame,
        m15_prev_close: datetime,
        m15_current_close: datetime,
    ) -> list[int]:
        if "time" not in m1_df.columns:
            return []
        close_times = pd.to_datetime(m1_df["time"], utc=True) + timedelta(minutes=1)
        mask = (close_times > m15_prev_close) & (close_times <= m15_current_close)
        positions = np.flatnonzero(mask.to_numpy())
        return [int(pos) for pos in positions]

    def _passes_regime_filter(self, m15_df: pd.DataFrame) -> bool:
        if self._regime_filter is None or not self._regime_filter.enabled:
            return True
        adx = calculate_adx(
            high=m15_df["high"].astype(float),
            low=m15_df["low"].astype(float),
            close=m15_df["close"].astype(float),
            period=self._regime_filter.adx_period,
        )
        if adx.empty:
            return False
        adx_value = float(adx.iloc[-1])
        if np.isnan(adx_value):
            return False
        return adx_value >= self._regime_filter.min_adx

    def _build_risk_context(
        self,
        m15_df: pd.DataFrame,
        direction: Direction,
        entry_price: float,
        m15_fast: float,
    ) -> tuple[float, float, float, float] | None:
        if self._risk_context is None or not self._risk_context.enabled:
            return None
        if len(m15_df) < self._risk_context.atr_period:
            return None
        atr = calculate_atr(
            high=m15_df["high"].astype(float),
            low=m15_df["low"].astype(float),
            close=m15_df["close"].astype(float),
            period=self._risk_context.atr_period,
        )
        if atr.empty:
            return None
        atr_value = float(atr.iloc[-1])
        if np.isnan(atr_value):
            return None
        stop_distance = atr_value * self._risk_context.atr_stop_multiplier
        rr1, rr2 = self._risk_context.rr_targets
        if direction is Direction.BUY:
            tp1 = entry_price + stop_distance * rr1
            tp2 = entry_price + stop_distance * rr2
        else:
            tp1 = entry_price - stop_distance * rr1
            tp2 = entry_price - stop_distance * rr2
        return (stop_distance, m15_fast, tp1, tp2)


@dataclass(frozen=True)
class _M1Context:
    df: pd.DataFrame
    lwma_fast: pd.Series
    lwma_slow: pd.Series
    stoch_k: pd.Series
    stoch_d: pd.Series


def _cross_at(series_a: pd.Series, series_b: pd.Series, idx: int) -> tuple[bool, bool]:
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
