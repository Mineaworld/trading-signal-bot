# Test Plan
# Trading Signal Bot - MT5 + Telegram

## 1. Test Strategy

### 1.1 Test Levels
| Level | Scope | Tools | Mocking |
|---|---|---|---|
| Unit | Individual functions, pure logic | pytest | No external calls |
| Replay | Startup replay correctness + dedup interaction | pytest | MT5 mocked, Telegram mocked |
| Integration | Module interactions, failure recovery | pytest | MT5 mocked, Telegram mocked |
| System (Manual) | End-to-end with real MT5 + Telegram | Manual run | None - real connections |

### 1.2 Test Coverage Targets
| Module | Target | Priority |
|---|---|---|
| `indicators/lwma.py` | 100% | High |
| `indicators/stochastic.py` | 100% | High |
| `strategy.py` | 100% | Critical |
| `repositories/dedup_store.py` | 100% | Critical |
| `mt5_client.py` | 80% (reconnect logic) | Medium |
| `telegram_notifier.py` | 80% (retry + queue) | Medium |
| `main.py` | 60% (loop orchestration) | Low |

---

## 2. Unit Tests

### 2.1 `test_lwma.py`

| Test Case | Input | Expected | Validates |
|---|---|---|---|
| Known values (period 3) | series=[1,2,3,4,5], period=3 | Hand-calculated LWMA values | Core math correctness |
| Known values (period 5) | series=[10,20,30,40,50], period=5 | Hand-calculated values | Longer period correctness |
| Constant series | series=[100]*10, period=3 | All LWMA values = 100 | Constant input invariant |
| Linear increase | series=[1..10], period=3 | LWMA follows trend, weighted to recent | Recency weighting |
| NaN warmup | series=[1,2,3], period=3 | First 2 values = NaN, 3rd = computed | Warmup period handling |
| Cross above | fast crosses above slow | crossed_above=True, crossed_below=False | Cross detection accuracy |
| Cross below | fast crosses below slow | crossed_above=False, crossed_below=True | Cross detection accuracy |
| No cross (parallel) | fast and slow move parallel | Both False | No false positives |
| Touch without cross | fast touches slow, no cross | Both False | Boundary precision |
| Order bullish | fast[-1] > slow[-1] | 'bullish' | Trend detection |
| Order bearish | fast[-1] < slow[-1] | 'bearish' | Trend detection |
| Order neutral | fast[-1] == slow[-1] | 'neutral' | Edge case |

### 2.2 `test_stochastic.py`

| Test Case | Input | Expected | Validates |
|---|---|---|---|
| Known values | Predetermined close series | Hand-calculated %K, %D | Core math (Close/Close + LWMA smoothing) |
| Flat market (div-by-zero) | close=[100]*50 | raw_k = 50.0 for all | Division guard |
| Buy zone boundary (10) | %K = 10.0 | stoch_in_zone = True | Inclusive lower bound |
| Buy zone boundary (20) | %K = 20.0 | stoch_in_zone = True | Inclusive upper bound |
| Outside buy zone (21) | %K = 21.0 | stoch_in_zone = False | Zone exclusion |
| Sell zone boundary (80) | %K = 80.0 | stoch_in_zone = True | Inclusive lower bound |
| Sell zone boundary (90) | %K = 90.0 | stoch_in_zone = True | Inclusive upper bound |
| Cross above | %K crosses above %D | k_crossed_above_d = True | Cross detection |
| Cross below | %K crosses below %D | k_crossed_below_d = True | Cross detection |
| Close/Close mode | Uses close for range (not high/low) | Matches MT5 Close/Close output | Price field correctness |

### 2.3 `test_strategy.py`

| Test Case | Input | Expected | Validates |
|---|---|---|---|
| BUY S1 all gates pass | M15: bullish LWMA + stoch buy zone + cross; M1: stoch cross + buy zone | Signal(BUY, S1) | Happy path S1 |
| BUY S2 all gates pass | M15: bullish LWMA + stoch buy zone + cross; M1: LWMA cross above | Signal(BUY, S2) | Happy path S2 |
| SELL S1 all gates pass | M15: bearish LWMA + stoch sell zone + cross below; M1: stoch cross below + sell zone | Signal(SELL, S1) | Sell mirror |
| SELL S2 all gates pass | M15: bearish LWMA + stoch sell zone + cross below; M1: LWMA cross below | Signal(SELL, S2) | Sell mirror |
| M15 LWMA not bullish | M15 LWMA200 < LWMA350 for buy scenarios | None | Gate 1 rejection |
| M15 stoch not in zone | M15 %K = 50 (mid-range) | None | Gate 2 rejection |
| M15 stoch no cross | M15 %K parallel to %D | None | Gate 3 rejection |
| M1 stoch not in zone (S1) | M1 %K = 50 | None | Gate 5 rejection |
| M1 stale confirmation | M1 bar time outside M15 window | None | Time window enforcement |
| Priority: BUY S1 wins | Both BUY S1 and BUY S2 conditions met | Signal(BUY, S1) | Priority order |
| Priority: BUY over SELL | Both BUY and SELL conditions met | Signal(BUY, ...) | Priority order |
| NaN in decision bars | NaN in LWMA values | None | NaN guard |
| Insufficient bars | DataFrame < 350 rows | None (or skip) | Bar count guard |
| S2 requires trend filter | M15 stoch in buy zone + cross but LWMA bearish | None | S2 trend filter enforced |

### 2.4 `test_dedup_store.py`

| Test Case | Input | Expected | Validates |
|---|---|---|---|
| New signal passes both keys | Never-seen signal | should_emit = True | Fresh signal allowed |
| Idempotency blocks exact repeat | Same (symbol, dir, scenario, m15_bar) | should_emit = False | Idempotency key works |
| Cooldown blocks same direction | Same (symbol, dir) within 15 min | should_emit = False | Cooldown key works |
| Cooldown expires | Same (symbol, dir) after 15 min | should_emit = True | Cooldown expiry |
| Different scenario passes idem | Same symbol+dir but different scenario | Depends on cooldown | Key separation |
| Atomic write | Record signal, verify file updated | File contains new entry | Persistence correctness |
| Corrupt state recovery | Corrupt JSON file | State reset, backup created, log warning | Corruption handling |
| State survives reload | Record, create new DedupStore, load | Previous entries present | Restart persistence |

---

## 3. Replay Tests (`test_replay.py`)

| Test Case | Setup | Expected | Validates |
|---|---|---|---|
| No look-ahead in replay | 3 M15 bars, bar_2 has signal. Data sliced to bar_2 only. | Signal uses only data up to bar_2 | Look-ahead prevention |
| Replay sends missed signal | Bot was down during bar_2 signal. Replay runs. | Signal sent for bar_2 | Missed signal recovery |
| Dedup blocks already-alerted | bar_2 was already alerted before shutdown | should_emit = False for bar_2 | Dedup interaction |
| Replay with no signals | All 3 bars produce no signals | 0 alerts sent | No false positives |
| Replay order is chronological | Bars replayed oldest to newest | Signals evaluated in time order | Ordering correctness |

---

## 4. Integration Tests

### 4.1 `test_mt5_client_resilience.py`

| Test Case | Setup | Expected | Validates |
|---|---|---|---|
| Reconnect after disconnect | Mock MT5 fails 2x then succeeds | Connected after 3rd attempt | Backoff + reconnect |
| All retries exhausted | Mock MT5 fails 5x | reconnect returns False | Max retry behavior |
| Fetch after reconnect | Disconnect, reconnect, fetch | DataFrame returned | Recovery completeness |
| Symbol alias resolution | Config: XAUUSD -> XAUUSDm | MT5 called with XAUUSDm | Alias mapping |
| Invalid symbol hard-fail | Alias maps to non-existent symbol | validate returns False | Startup check |

### 4.2 `test_notifier_retry.py`

| Test Case | Setup | Expected | Validates |
|---|---|---|---|
| Send succeeds first try | Mock Telegram returns 200 | send_signal returns True | Happy path |
| Send succeeds on retry 2 | Mock fails 1x then succeeds | send_signal returns True | Retry logic |
| All retries fail, queued | Mock fails 3x | Signal added to failed queue file | Queue fallback |
| RetryAfter respected | Mock returns RetryAfter(5) | Wait 5s then retry | Rate limit handling |
| Queue retry succeeds | Queue has 1 signal, mock succeeds | Queue emptied, signal sent | Queue drain |
| Queue max size enforced | Queue has 50, add 51st | Oldest dropped, size = 50 | FIFO eviction |
| Startup message validates | Mock Telegram returns 200 | send_startup_message returns True | Boot check |

---

## 5. System Test (Manual Verification)

### 5.1 Verification Checklist

| # | Test | How to Verify | Pass Criteria |
|---|---|---|---|
| 1 | All automated tests pass | `pytest tests/` | 0 failures |
| 2 | Dry-run mode works | `python -m poetry run trading-signal-bot --dry-run` | Signals print to console, no Telegram |
| 3 | MT5 candle fetch works | Check logs for DataFrame shape | 450 bars per symbol, UTC timestamps |
| 4 | Symbol alias works | Change XAUUSD to XAUUSDm in config | Bot uses XAUUSDm for MT5, XAUUSD in logs |
| 5 | Tradability gate works | Run during weekend | Symbols skipped, logged as not tradable |
| 6 | Telegram delivery works | Run during market hours | Alert received in Telegram with correct format |
| 7 | Dedup persists across restart | Kill bot, restart | No duplicate alert for same M15 bar |
| 8 | Restart replay works | Kill bot for 30+ min, restart | Missed signals sent (if any triggered) |
| 9 | Stale M1 rejected | `pytest tests/unit/test_strategy.py -k m1_stale_rejected` | Test passes and no signal is emitted for stale M1 window |
| 10 | Reconnect works | Temporarily disconnect internet, reconnect | Bot recovers, no crash, logs show reconnect |
| 11 | First 50 alerts accurate | Compare each alert against MT5 chart | All signals match visual chart conditions |

---

## 6. Test Data Strategy

### 6.1 Fixtures (`conftest.py`)

```python
# Synthetic M15 DataFrame that triggers BUY S1
@pytest.fixture
def m15_buy_s1_df() -> pd.DataFrame:
    """450-bar M15 DataFrame where:
    - LWMA200 > LWMA350 (bullish)
    - Stoch %K in [10, 20]
    - Stoch %K crosses above %D on last closed bar"""

# Synthetic M1 DataFrame that confirms BUY S1
@pytest.fixture
def m1_buy_s1_confirm_df() -> pd.DataFrame:
    """450-bar M1 DataFrame where:
    - Stoch %K crosses above %D
    - Stoch %K in [10, 20]
    - Bar time within M15 window"""

# Flat market DataFrame
@pytest.fixture
def flat_df() -> pd.DataFrame:
    """DataFrame with constant close price. Tests division-by-zero guard."""

# Stale M1 DataFrame (outside M15 window)
@pytest.fixture
def stale_m1_df() -> pd.DataFrame:
    """M1 DataFrame where all bars are from a previous M15 period."""
```
