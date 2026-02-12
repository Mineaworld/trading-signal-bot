# Technical Specification
# Trading Signal Bot - MT5 + Telegram

## 1. API Contracts

### 1.1 Internal Module APIs

#### `mt5_client.MT5Client`

```python
class MT5Client:
    def __init__(self, login: int, password: str, server: str,
                 path: str | None, alias_map: dict[str, str],
                 reconnect: ReconnectConfig,
                 mt5_module: Any | None = None) -> None

    def connect(self) -> bool
        """Initialize MT5 terminal. Returns True on success."""

    def disconnect(self) -> None
        """Shutdown MT5 terminal."""

    def is_connected(self) -> bool
        """Check terminal connection via mt5.terminal_info()."""

    def reconnect(self) -> bool
        """Exponential backoff with jitter. Max 5 retries.
        Delays: 1s, 2s, 4s, 8s, 16s (capped at 30s).
        Jitter: random 0-500ms added to each delay.
        Returns True if reconnected, False if all retries exhausted."""

    def fetch_candles(self, symbol: str, timeframe: Timeframe,
                      count: int = 450) -> pd.DataFrame
        """Fetch OHLC bars. Symbol is alias - resolved internally.
        Returns DataFrame with columns: time(UTC), open, high, low, close, tick_volume.
        Raises RuntimeError if symbol unavailable."""

    def get_current_price(self, symbol: str) -> float | None
        """Return last tick close price. None if unavailable."""

    def validate_symbol_aliases(self, alias_map: dict[str, str] | None = None) -> dict[str, bool]
        """Check each broker_symbol exists in MT5.
        Returns {alias: True/False}."""

    def is_symbol_tradable(self, symbol: str) -> bool
        """Check mt5.symbol_info(broker_symbol).trade_mode.
        Returns True if symbol is currently tradable."""
```

#### `indicators.lwma`

```python
def calculate_lwma(series: pd.Series, period: int) -> pd.Series
    """Linear Weighted Moving Average.
    Weights: [1, 2, 3, ..., period]. Most recent bar = highest weight.
    Returns Series with NaN for first (period-1) values."""

def lwma_cross(fast: pd.Series, slow: pd.Series) -> tuple[bool, bool]
    """Detect crossover on two most recent CLOSED bars (iloc[-2], iloc[-1]).
    Returns (crossed_above, crossed_below).
    crossed_above: fast[-2] <= slow[-2] AND fast[-1] > slow[-1]"""

def lwma_order(fast: pd.Series, slow: pd.Series) -> str
    """Returns 'bullish' if fast[-1] > slow[-1],
    'bearish' if fast[-1] < slow[-1], else 'neutral'.
    Uses last closed bar (iloc[-1])."""
```

#### `indicators.stochastic`

```python
def calculate_stochastic(close: pd.Series, k_period: int = 30,
                         d_period: int = 10, slowing: int = 10
                         ) -> tuple[pd.Series, pd.Series]
    """Stochastic Oscillator with Close/Close and LWMA smoothing.
    Step 1: raw_k = (close - lowest_close) / (highest_close - lowest_close) * 100
    Step 2: %K = LWMA(raw_k, slowing)    <- main line (red)
    Step 3: %D = LWMA(%K, d_period)      <- signal line (black)
    Division-by-zero: raw_k = 50.0 when highest == lowest.
    Returns (percent_k, percent_d)."""

def stoch_cross(k: pd.Series, d: pd.Series) -> tuple[bool, bool]
    """Cross detection on last two closed bars.
    Returns (k_crossed_above_d, k_crossed_below_d)."""

def stoch_in_zone(k_value: float, zone: tuple[int, int]) -> bool
    """Returns True if zone[0] <= k_value <= zone[1]. Inclusive."""
```

#### `strategy.StrategyEvaluator`

```python
class StrategyEvaluator:
    def __init__(self, params: IndicatorParams) -> None

    def m15_requires_m1(self, m15_df: pd.DataFrame,
                        m15_close_time_utc: datetime) -> bool

    def evaluate(self, m15_df: pd.DataFrame, m1_df: pd.DataFrame,
                 symbol: str, m15_close_time_utc: datetime,
                 price: float | None = None
                 ) -> Signal | None
        """Run all 4 scenarios in priority order. Return first match or None.
        Priority: BUY_S1 > BUY_S2 > SELL_S1 > SELL_S2.
        M1 time window enforced: m15_prev_close < m1_bar_time <= m15_current_close."""

    def evaluate_m1_only(self, m1_df: pd.DataFrame,
                         symbol: str, price: float | None = None) -> Signal | None
        """Evaluate optional M1-only BUY_M1/SELL_M1 scenarios."""
```

#### `repositories.dedup_store.DedupStore`

```python
class DedupStore:
    def __init__(self, state_file: Path, cooldown_minutes: int,
                 retention_days: int) -> None

    def load_state(self) -> dict
        """Load from JSON. On corruption: restore backup, reset, log warning."""

    def should_emit(self, signal: Signal) -> bool
        """Check BOTH keys:
        1. idempotency_key = (symbol, direction, scenario, bar_time)
           where bar_time uses m15_bar_time_utc, or falls back to m1_bar_time_utc
        2. cooldown_key = (symbol, direction) within cooldown_minutes
        Returns True if signal should be sent (neither key blocks it)."""

    def record(self, signal: Signal) -> None
        """Persist both keys. Atomic write: write to .tmp, then os.replace()."""
```

#### `telegram_notifier.TelegramNotifier`

```python
class TelegramNotifier:
    def __init__(self, token: str, chat_id: str,
                 failed_queue_file: Path, max_queue: int = 50,
                 max_retries: int = 3,
                 max_failed_retry_count: int = 12,
                 timeout_seconds: int = 15,
                 dry_run: bool = False,
                 session: requests.Session | None = None) -> None

    def send_signal(self, signal: Signal) -> bool
        """Format HTML, send via Bot API. Retry 3x.
        On RetryAfter: wait retry_after seconds.
        On final failure: queue to failed_signals.json.
        Returns True if sent successfully."""

    def send_startup_message(self) -> bool
        """Send test message on boot. Validates token + chat_id."""

    def retry_failed_queue(self) -> int
        """Retry all signals in failed queue. Returns count of successful retries."""
```

---

## 2. Data Formats

### 2.1 Signal JSON (for dedup persistence)

```json
{
  "idempotency_keys": {
    "XAUUSD|BUY|BUY_S1|2026-02-11T14:30:00Z": {
      "signal_id": "a1b2c3d4",
      "recorded_at": "2026-02-11T14:30:05Z"
    }
  },
  "cooldown_keys": {
    "XAUUSD|BUY": {
      "last_emitted": "2026-02-11T14:30:05Z"
    }
  }
}
```

### 2.2 Failed Signal Queue JSON

```json
[
  {
    "signal": {
      "id": "a1b2c3d4",
      "symbol": "XAUUSD",
      "direction": "BUY",
      "scenario": "BUY_S1",
      "price": 2341.50,
      "created_at_utc": "2026-02-11T14:30:05Z",
      "m15_bar_time_utc": "2026-02-11T14:30:00Z",
      "m1_bar_time_utc": "2026-02-11T14:29:00Z",
      "m15_lwma_fast": 2338.20,
      "m15_lwma_slow": 2335.10,
      "m15_stoch_k": 15.4,
      "m15_stoch_d": 12.8,
      "m1_stoch_k": 18.2,
      "m1_stoch_d": 14.5
    },
    "failed_at": "2026-02-11T14:30:08Z",
    "retry_count": 3,
    "last_error": "ConnectionError: Telegram API unreachable"
  }
]
```

### 2.3 Telegram Alert HTML Format

```html
<b>BUY XAUUSD</b>
<b>Scenario 1</b> (Stoch -> Stoch)

<b>Price:</b> 2,341.50
<b>Time:</b> 2026-02-11 14:30 UTC

<b>M15 Indicators:</b>
|- LWMA 200: 2,338.20
|- LWMA 350: 2,335.10
|- Stoch %K: 15.4
|- Stoch %D: 12.8

<b>M1 Confirmation:</b>
|- Stoch %K: 18.2
|- Stoch %D: 14.5

#XAUUSD #BUY #S1
```

---

## 3. Algorithm Specifications

### 3.1 LWMA Calculation

```
Input:  series[0..n], period P
Output: lwma[0..n] (NaN for indices 0..P-2)

weights = [1, 2, 3, ..., P]
denominator = P * (P + 1) / 2

For each index i >= P-1:
    lwma[i] = sum(series[i-P+1+j] * weights[j] for j in 0..P-1) / denominator
```

### 3.2 Stochastic Calculation (Close/Close, LWMA-smoothed)

```
Input:  close[0..n], k_period=30, d_period=10, slowing=10
Output: percent_k[0..n], percent_d[0..n]

Step 1 - Raw %K:
    For each index i >= k_period-1:
        lowest  = min(close[i-k_period+1 .. i])
        highest = max(close[i-k_period+1 .. i])
        if highest == lowest:
            raw_k[i] = 50.0  # flat market guard
        else:
            raw_k[i] = (close[i] - lowest) / (highest - lowest) * 100

Step 2 - Smoothed %K (main line / red):
    percent_k = LWMA(raw_k, slowing)

Step 3 - %D (signal line / black):
    percent_d = LWMA(percent_k, d_period)
```

### 3.3 Cross Detection

```
Input:  line_a[0..n], line_b[0..n]
Output: (crossed_above: bool, crossed_below: bool)

Uses two most recent CLOSED bars: index -2 (previous) and -1 (current)

crossed_above = (line_a[-2] <= line_b[-2]) AND (line_a[-1] > line_b[-1])
crossed_below = (line_a[-2] >= line_b[-2]) AND (line_a[-1] < line_b[-1])
```

### 3.4 Smart Sleep Calculation

```
Input:  current_time_utc
Output: seconds_to_sleep

next_m15_close = current_time rounded UP to next 15-minute boundary
seconds_to_sleep = (next_m15_close - current_time).total_seconds()
if seconds_to_sleep <= 0:
    seconds_to_sleep = 1  # safety minimum
```

### 3.5 Dual-Key Dedup Logic

```
Input:  signal, state, cooldown_minutes
Output: should_emit (bool)

bar_time = signal.m15_bar_time_utc if present else signal.m1_bar_time_utc
idempotency_key = f"{signal.symbol}|{signal.direction}|{signal.scenario}|{bar_time}"
cooldown_key = f"{signal.symbol}|{signal.direction}"

# Check 1: exact duplicate
if idempotency_key in state.idempotency_keys:
    return False  # already fired for this exact setup

# Check 2: same-direction cooldown
if cooldown_key in state.cooldown_keys:
    elapsed = now - state.cooldown_keys[cooldown_key].last_emitted
    if elapsed < cooldown_minutes:
        return False  # too soon for same direction

return True  # signal is new and outside cooldown
```

### 3.6 Restart Replay Logic

```
Input:  symbols, mt5_client, strategy, dedup_store
Output: signals sent (count)

For each symbol in symbols:
    bars = mt5_client.fetch_candles(symbol, M15, count=450)
    last_3_closed = bars.iloc[-4:-1]  # 3 most recent closed bars

    For each bar in last_3_closed:
        # Slice data up to this bar only (prevent look-ahead)
        m15_slice = bars[bars['time'] <= bar['time']]
        m1_bars = mt5_client.fetch_candles(symbol, M1, count=450)
        m1_slice = m1_bars[m1_bars['time'] <= bar['time']]

        signal = strategy.evaluate(m15_slice, m1_slice, symbol, bar['time'])
        if signal and dedup_store.should_emit(signal):
            telegram.send_signal(signal)
            dedup_store.record(signal)
```

---

## 4. Configuration Schema

### 4.1 settings.yaml Schema

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbols` | dict[str, str] | Yes | - | Alias -> broker symbol mapping |
| `timeframes.primary` | str | Yes | M15 | Primary evaluation timeframe |
| `timeframes.confirmation` | str | Yes | M1 | Confirmation timeframe |
| `indicators.lwma.fast` | int | Yes | 200 | Fast LWMA period |
| `indicators.lwma.slow` | int | Yes | 350 | Slow LWMA period |
| `indicators.stochastic.k` | int | Yes | 30 | %K period |
| `indicators.stochastic.d` | int | Yes | 10 | %D period |
| `indicators.stochastic.slowing` | int | Yes | 10 | Slowing period |
| `indicators.stochastic.buy_zone` | list[int] | Yes | [10,20] | Buy zone bounds |
| `indicators.stochastic.sell_zone` | list[int] | Yes | [80,90] | Sell zone bounds |
| `data.candle_buffer` | int | Yes | 450 | Bars to fetch per request |
| `data.min_valid_closed_bars` | int | Yes | 2 | Parsed config value; currently reserved (not enforced in runtime strategy flow) |
| `execution.reconnect_max_retries` | int | Yes | 5 | MT5 reconnect attempts |
| `execution.reconnect_base_delay_seconds` | int | Yes | 1 | Initial backoff delay |
| `execution.reconnect_max_delay_seconds` | int | Yes | 30 | Max backoff delay |
| `execution.loop_failure_sleep_seconds` | int | Yes | 60 | Sleep after loop error |
| `signal_dedup.cooldown_minutes` | int | Yes | 15 | Same-direction cooldown |
| `signal_dedup.retention_days` | int | Yes | 14 | Days to keep dedup entries |
| `signal_dedup.state_file` | str | Yes | data/dedup_state.json | Dedup state path |
| `logging.level` | str | Yes | INFO | Log level |
| `logging.file` | str | Yes | logs/bot.log | Log file path |
| `logging.max_bytes` | int | Yes | 5242880 | Max log file size (5MB) |
| `logging.backup_count` | int | Yes | 3 | Rotated log file count |
| `telegram.failed_queue_file` | str | Yes | data/failed_signals.json | Failed queue path |
| `telegram.max_queue_size` | int | Yes | 50 | Max queued failed signals |
| `telegram.max_retries` | int | Yes | 3 | Send retry count |
| `telegram.max_failed_retry_count` | int | Yes | 12 | Max retries from failed queue |
| `telegram.request_timeout_seconds` | int | Yes | 15 | HTTP request timeout |
| `m1_only.enabled` | bool | No | false | Enable M1-only signal evaluation |

### 4.2 .env Schema

| Key | Type | Required | Description |
|---|---|---|---|
| `MT5_LOGIN` | int | Yes | MT5 account number |
| `MT5_PASSWORD` | str | Yes | MT5 account password |
| `MT5_SERVER` | str | Yes | MT5 broker server name |
| `MT5_TERMINAL_PATH` | str | No | Path to terminal64.exe (auto-detected if not set) |
| `TELEGRAM_BOT_TOKEN` | str | Yes | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | str | Yes | Target chat/group ID |
