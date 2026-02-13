# Bot Failure Scenarios and Risk Register

Last updated: 2026-02-13

## Scope

This document lists practical failure modes for the current bot design and codebase.
No document can cover literally every theoretical failure in an open system, but this
is intended to be exhaustive for real-world operation of this project.

System covered:

- MT5 connectivity and candle ingestion
- Strategy evaluation and signal generation
- Dedup state and retry queue persistence
- Telegram delivery pipeline
- Runtime/process/infrastructure operations

## Severity and Likelihood Scale

- Severity:
  - `Critical`: Signal pipeline can stop, silently lose alerts, or create large trust damage.
  - `High`: Misses or delays meaningful signals, or creates repeated noise.
  - `Medium`: Degrades quality, but bot still functions.
  - `Low`: Annoying or cosmetic; limited direct trading impact.
- Likelihood:
  - `High`: Expected to happen in normal operations eventually.
  - `Medium`: Happens under specific but realistic conditions.
  - `Low`: Rare edge case.

---

## 1) Startup and Configuration Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| S01 | MT5 Python package unavailable | Running on unsupported environment or missing dependency | Startup exception from MT5 client init | Bot never starts | Critical | Medium | Raises runtime error immediately | Install `MetaTrader5` and run on supported Windows MT5 environment |
| S02 | MT5 terminal initialization fails | Bad terminal path or terminal not installed | `startup failed: cannot connect/login MT5` | Bot never starts | Critical | Medium | Hard-fail at startup | Fix `MT5_TERMINAL_PATH` and MT5 installation |
| S03 | MT5 login fails | Wrong login/password/server | Same startup failure as above | Bot never starts | Critical | Medium | Hard-fail at startup | Correct `.env` credentials; test login manually in terminal |
| S04 | Missing required env vars | Incomplete `.env` | Startup throws missing variable error | Bot never starts | Critical | Medium | Hard-fail in `load_secrets` | Populate all required `.env` keys |
| S05 | Invalid env types | Non-integer `MT5_LOGIN` | Startup `ValueError` | Bot never starts | High | Low | Hard-fail at startup | Use valid integer values in `.env` |
| S06 | `settings.yaml` missing | File removed or wrong path | Startup file-not-found | Bot never starts | Critical | Low | Hard-fail loading config | Restore `config/settings.yaml` or pass `--config` |
| S07 | Invalid YAML schema | Missing sections/wrong types | Startup config parse error | Bot never starts | Critical | Low | Hard-fail in config validation | Fix config keys and types |
| S08 | Invalid indicator config | Bad zone bounds or non-positive periods | Startup parse error | Bot never starts | High | Low | Hard-fail validation | Keep periods and zones valid |
| S09 | Alias mapping unresolved | Broker symbol wrong (e.g., `NAS100` mismatch) | `startup failed: unresolved symbol aliases` | Bot never starts | Critical | Medium | Hard-fail after alias validation | Fix `symbols` mapping to broker-specific codes |
| S10 | Telegram startup check fails | Wrong token/chat id/network blocked | `startup failed: telegram startup check failed` | Bot never starts | Critical | Medium | Hard-fail on startup check | Fix token/chat ID/network; verify bot in target chat |
| S11 | Lock file exists for running instance | Duplicate bot process | `lock file already exists` | Second process cannot start | Low | Medium | Prevents second instance | Keep one instance; stop existing process first |
| S12 | Lock file cleanup blocked | File permission issues | Startup lock acquisition failure | Bot never starts | High | Low | Raises runtime error | Fix file permissions for `data/` |
| S13 | Log directory not writable | Permission/disk issue | Startup or runtime logging errors | Reduced observability, possible crash | Medium | Medium | Logger setup may fail | Ensure write access to `logs/` |
| S14 | Data directory not writable | Permission/disk issue | Dedup/queue write failures | Duplicates, missed retries, potential crashes | High | Medium | Writes can raise exceptions | Ensure write access to `data/` |
| S15 | Disk full at startup | Host storage exhausted | Fails to write state/log/queue | Bot unstable or fails to start | High | Medium | No dedicated disk guard | Monitor free space and alert early |
| S16 | Startup replay fails for symbol | Any exception in replay loop | `startup replay failed for symbol=...` log | Missed replay recovery for that symbol | Medium | Medium | Exception caught, process continues | Investigate logs, rerun after fixing root cause |
| S17 | Startup with insufficient bars | Fresh market open/history not loaded | Replay sends nothing | Missed catch-up alerts | Medium | High | Replay skips if not enough bars | Open charts in MT5 to preload history |
| S18 | Incorrect timeframe config | Timeframe value not in enum | Startup parse error | Bot never starts | High | Low | Hard-fail during config load | Use supported values (`M15`, `M1`) |

---

## 2) MT5 Data and Market Interface Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| D01 | Symbol not tradable | Market closed or trade mode disabled | `symbol not tradable, skipping` | No evaluation for that symbol | Medium | High | Skips symbol safely | Expected behavior; monitor sessions per symbol |
| D02 | MT5 disconnected during run | Terminal/API disconnect | Runtime errors then reconnect attempts | Missed cycles during outage | High | Medium | Reconnect with backoff | Keep MT5 stable; VPS and network hardening |
| D03 | Reconnect retries exhausted | Long broker/API outage | Repeated symbol processing exceptions | Persistent missed signals | Critical | Medium | Loop continues; retries later | Alert on repeated reconnect failure in logs |
| D04 | Candle fetch returns empty | Broker history/API issue | Runtime error fetching candles | Symbol skipped | High | Medium | Raises and caught at symbol level | Validate broker feed availability |
| D05 | MT5 response missing required columns | API contract anomaly | Runtime error about missing columns | Symbol skipped | High | Low | Raises explicit error | Upgrade MT5 client and inspect broker/API |
| D06 | Candle timestamps stale | MT5 stopped updating while connected | Repeated old `m15_close` processing state | Silent signal misses | High | Medium | No explicit stale-feed guard | Add stale timestamp watchdog |
| D07 | Runtime misses intermediate M15 bars | Bot delayed >15 min (load/freeze/network) | Only latest closed bar processed | Potential lost signals between closes | High | Medium | No runtime backfill (startup replay only) | Add in-loop backfill window, not only startup replay |
| D08 | Host sleep/hibernate | Local machine power policy | Gaps in operation | Missed signals during sleep | High | High (local PC) | Resumes without full gap replay except startup only | Use VPS or disable sleep |
| D09 | System clock drift | Bad time sync/NTP issues | Wrong sleep timing, delayed cycles | Missed or delayed checks | High | Low | Uses local UTC clock | Enable NTP and monitor drift |
| D10 | Current tick price unavailable | `symbol_info_tick` returns `None` | Alert price may fall back to bar close | Slight alert price mismatch | Low | Medium | Uses candle close fallback | Acceptable; optional retry tick fetch |
| D11 | Insufficient M15 bars | Monday open/history gap | `insufficient M15 bars` warning | No signals until history warms | Medium | High | Skips safely | Keep MT5 chart history loaded |
| D12 | Insufficient M1 bars | Monday open/history gap | No M1 confirmation | No signal though setup may be near | Medium | High | Strategy returns `None` | Ensure at least 350+ bars history |
| D13 | Unexpected API latency spike | Broker/network slow responses | Processing drifts from close boundary | Signal delay | Medium | Medium | Sequential loop waits naturally | Use stable VPS near broker server |
| D14 | Wrong alias maps to wrong instrument | Misconfigured `symbols` map | Signals look inconsistent vs expected chart | False trust in alerts | Critical | Medium | Alias is trusted after existence check | Validate each alias manually against intended market |
| D15 | Broker maintenance window | Scheduled downtime | Reconnect/candle failures | Temporary missed signals | Medium | Medium | Retry each cycle | Accept and monitor maintenance schedules |
| D16 | MT5 terminal GUI blocked | Modal dialog/update prompt | API calls fail/hang | Pipeline outage | High | Low | No explicit watchdog | Keep MT5 auto-update and dialogs controlled |

---

## 3) Strategy Logic and Signal Quality Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| Q01 | Desktop indicator mismatch | Different MT5 indicator params/methods | Bot alert differs from chart indicator | Trust erosion | High | Medium | Bot uses its own calculations | Match chart settings exactly to bot config |
| Q02 | Cross interpretation mismatch | Equality edge cases (`<=` / `>=`) | "I see cross, bot didn't" or reverse | Signal disagreement | Medium | Medium | Deterministic cross function | Document exact cross rule and stick to it |
| Q03 | Stochastic method mismatch | Chart not using Close/Close + LWMA smoothing | Different %K/%D values | Signal disagreement | High | Medium | Bot uses fixed formula from code/config | Align desktop stochastic method to bot method |
| Q04 | Zone boundary sensitivity | `%K` just outside [10,20] or [80,90] | Near-miss non-signals | Opportunity miss | Medium | High | Strict inclusive zone checks | Tune zones after validation/backtest |
| Q05 | Latest-M1-only confirmation | Earlier M1 cross in window but latest M1 bar no longer confirms | No signal despite intra-window setup | Missed setups | High | Medium | Uses last M1 close in M15 window | Add optional scanning of full window instead of last bar only |
| Q06 | M1 polling lag under host stress | CPU/network delays cause minute-loop drift | Late M1-only evaluation and possible skipped opportunities during long lag | Missed M1 opportunities | Medium | Medium | Runs M1-only on 1-minute cadence with cursor catch-up | Add loop latency monitoring + host resource watchdog |
| Q07 | Scenario priority masks alternatives | Multiple conditions true same bar | Only one scenario emitted | Partial context loss | Low | Medium | Priority fixed (`BUY_S1 > BUY_S2 > SELL_S1 > SELL_S2`) | Include secondary scenario metadata if needed |
| Q08 | M15 preconditions gate M1 fetch | M15 gate false due tiny value changes | No M1 checks | Possible conservative misses | Medium | Medium | Intentional lazy design | Accept as strategy policy or relax gating |
| Q09 | Cooldown suppresses legitimate same-direction setup | New valid setup inside 15 minutes | "signal blocked by dedup" | Missed valid entry alerts | High | Medium | Direction-level cooldown key | Tune cooldown or make scenario-aware cooldown |
| Q10 | Idempotency suppresses re-alert for same bar | Restart/replay same setup | No duplicate (expected) | May look like missed alert if user deleted message | Low | High | Intentional | Keep as anti-spam behavior |
| Q11 | M1-only mode noise | Enabling `m1_only.enabled=true` | More frequent low-quality alerts | Lower signal quality | High | Medium | Explicitly tagged low confidence | Keep disabled for primary decisioning |
| Q12 | M1-only overtrading/noise | 1-minute cadence increases candidate frequency | More low-confidence alerts and user fatigue | Lower decision quality | High | Medium | Signals are labeled low confidence + dedup cooldown applies | Tighten filters or keep M1-only disabled for primary ops |
| Q13 | Price mismatch vs execution reality | Alert price from current tick or close, not actual fill | Manual trade PnL variance | Medium | High | Uses best available tick/close | Treat alerts as setup, not exact fill price |
| Q14 | No spread/slippage/news filter | Volatile market events | More false/poor entries | Trading underperformance | High | High | Not in v1 scope | Add regime/news/volatility filters |
| Q15 | No auto execution | User delayed response | Missed entries even if alert is good | Medium | High | Alert-only design | Use alerts for awareness; consider later automation |
| Q16 | Regime shift risk | Strategy stops fitting market regime | Declining win rate | High | Medium | No adaptive logic | Add performance monitoring and periodic revalidation |
| Q17 | Limited replay horizon | Downtime > ~45 minutes | Older missed setups unrecoverable | High | Medium | Replays only last 3 M15 bars | Increase replay depth or persistent cursor |
| Q18 | Manual chart-time misunderstanding | User reads local time while bot reports UTC | "Wrong candle" confusion | Low | High | Alerts formatted in UTC | Educate on UTC or add local-time option |

---

## 4) Alert Delivery and Queue Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| A01 | Telegram request timeout | Network instability | Send fails; retries happen | Delay or queueing | Medium | Medium | Retries then queue | Improve network path and timeout tuning |
| A02 | Telegram rate limited (429) | Bursty sends | Retry with `retry_after` | Delay | Medium | Medium | Honors retry-after | Keep send volume low; batch if needed |
| A03 | Telegram non-200 responses | API/client errors | Failed send logs | Delay or drop after max retries | High | Medium | Retry then queue | Monitor logs and token/chat health |
| A04 | Long Telegram outage | API unreachable for hours | Queue keeps growing | Backlog and delayed alerts | High | Medium | Queue with max size | Add external outage alerting |
| A05 | Queue reaches max size | Too many unsent alerts | Oldest entries dropped | Permanent alert loss | Critical | Medium | Keeps newest `max_queue_size` only | Increase size and add secondary durable store |
| A06 | Max failed retry count reached | Persistent send failure per item | Item dropped from queue | Permanent alert loss | High | Medium | Drops after configured retries | Raise threshold and fix root cause quickly |
| A07 | Failed queue file corruption | Manual edit/crash partial write | `.corrupt` backup, queue reset | Loses pending failed alerts | High | Low | Backup + reset | Protect file system; backup queue externally |
| A08 | Wrong chat target | Wrong `TELEGRAM_CHAT_ID` | Alerts sent to unexpected chat | Silent operational failure | Critical | Medium | Startup only checks send success, not recipient intent | Verify chat ID in production checklist |
| A09 | Bot removed from chat later | Permissions changed post-startup | Send failures after startup | Delayed/dropped alerts | High | Medium | Retry/queue behavior applies | Monitor ongoing send success metrics |
| A10 | Dry-run accidentally enabled | Operator starts with `--dry-run` | Logs show DRY RUN, no real Telegram alerts | Total alert loss in production | Critical | Medium | Dry run returns success intentionally | Add startup banner/guard for prod mode |
| A11 | Crash between dedup record and send | Process killed after `dedup.record` and before queue persistence | No alert sent; future duplicate blocked | Silent lost alert | Critical | Low | No transactional coupling between dedup and send | Record after successful send or implement atomic outbox pattern |
| A12 | Retry cadence too slow | Queue retries only every M15 cycle | Failed alerts retried late | Delay in recovery | Medium | High | Retries once per loop cycle | Separate retry timer for queue |

---

## 5) Dedup, State, and File System Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| P01 | Dedup state file corruption | Disk issues/manual edit/crash | Backup created; state reset | Potential duplicate alerts after reset | High | Low | Auto backup + reset | Keep periodic backup of dedup file |
| P02 | Dedup file unwritable | Permission/disk full | Record/write exceptions | Possible crash path or duplicate risk | High | Medium | No dedicated recovery around every write failure | Ensure writable persistent storage |
| P03 | Dedup retention too short | Misconfigured `retention_days` | Older keys pruned early | Re-alert duplicates over longer windows | Medium | Medium | Config-driven prune | Tune retention to your operating horizon |
| P04 | Cooldown too long | Misconfigured cooldown minutes | Legit setups blocked too often | Performance degradation | High | Medium | Config-driven gate | Tune and validate statistically |
| P05 | Cooldown too short | Aggressive setting | More alert spam | Noise/fatigue | Medium | Medium | Config-driven gate | Tune by observed signal density |
| P06 | Manual deletion of dedup state | Operator action | Bot "forgets" sent signals | Duplicate re-alerts | Medium | Medium | No protection against manual deletion | Restrict file access; include op runbook |
| P07 | Multiple instances using different lock paths | Custom `--lock-file` misuse | Duplicate alerts from parallel instances | Critical | Low | Lock only protects chosen path | Standardize lock-file path in deployment scripts |
| P08 | PID edge-case lock behavior | Rare OS/PID reuse scenario | False lock conflict or missed lock conflict | Start/duplication risk | Medium | Low | PID-based stale lock cleanup | Keep one controlled service manager |
| P09 | Queue file unwritable | Permission/disk issue | Failed sends cannot be persisted | Permanent signal loss under outages | Critical | Medium | No alternate sink | Add secondary durable sink and disk checks |
| P10 | Antivirus/backup software locks files | External process interference | Intermittent write failures | Lost or delayed state updates | Medium | Low | No specific handling | Exclude data/log paths from aggressive locks |

---

## 6) Runtime, Host, and Infrastructure Failures

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Behavior | Mitigation |
|---|---|---|---|---|---|---|---|---|
| O01 | Host reboot/power loss | Windows update/power issue | Bot down until restart | Missed signals during downtime | High | Medium | Startup replay only last 3 M15 bars | Run as managed service + larger recovery window |
| O02 | Internet outage | ISP/VPS network issue | MT5 and Telegram failures | No new alerts | Critical | Medium | Retries and queueing where possible | Multi-network/VPS reliability measures |
| O03 | DNS failure | Resolver issues | Telegram/MT5 unreachable | No alerts | High | Low | Treated as request failures | Use reliable DNS and host-level monitoring |
| O04 | Resource exhaustion | CPU/RAM pressure | Slow cycles, delayed processing | Missed timing windows | High | Medium | No built-in resource watchdog | Monitor host resource usage and restart policy |
| O05 | Process freeze/hang | External lib/OS issue | No new logs, no alerts | Silent outage | Critical | Low | No heartbeat check built in | Add watchdog heartbeat and auto-restart |
| O06 | Unhandled loop exception storms | Repeating unexpected errors | Repeated `loop error` + sleeps | Extended degraded service | High | Medium | Sleeps then retries loop | Add alerting on repeated loop failures |
| O07 | MT5 terminal updates or popups | Auto-update events | API unavailable/hangs | Interruption | High | Low | No popup automation | Freeze MT5 update window on production host |
| O08 | Firewall or policy change | Outbound blocked | Telegram/MT5 failures | No alerts | High | Medium | Retries but no route | Pin required outbound rules |
| O09 | Deployment drift | Running outdated config/code | Behavior differs from expected | Medium to high | Medium | High | No version pinning runtime check | Use release tagging + startup version log |
| O10 | Secrets leak risk | `.env` exposure | Unauthorized account/API use | Critical security event | Critical | Low | Secrets externalized but local file based | Tight file permissions and secret rotation |
| O11 | No external uptime alerting | Bot dies silently | User notices late | Missed opportunities | High | High | No built-in external notifier | Add health ping/heartbeat monitor |

---

## 7) Testing and Validation Gaps (Can Cause False Confidence)

| ID | Scenario | Trigger | Observable Symptom | Impact | Severity | Likelihood | Current Status | Mitigation |
|---|---|---|---|---|---|---|---|---|
| T01 | No completed production backtest pipeline | v2 scope not finished | Unknown expected edge before live | Strategy risk unknown | High | High | Planned, not fully operational for decisioning | Complete historical + forward validation cycle |
| T02 | Synthetic tests differ from real broker feed quirks | Real-world candle anomalies | Live behavior diverges from tests | Medium | Medium | Unit/integration tests exist with mocks | Add broker-data replay tests |
| T03 | No chaos testing for disk/network exhaustion | Rare infra events | Unexpected runtime behavior | High | Medium | Limited fault injection | Add failure-injection scripts |
| T04 | No statistical performance monitor | Win rate drifts over time | Slow unnoticed degradation | High | Medium | Manual validation oriented | Add rolling KPI dashboard |
| T05 | No automated reconciliation vs chart screenshots | Human error in validation | Misclassification of bot quality | Medium | Medium | Manual checks | Build semi-automated validation journal |

---

## 8) Top High-Priority Risks to Fix First

1. `A11` Crash window between dedup record and successful send can silently lose alerts.
2. `D07` Runtime does not backfill missed intermediate M15 bars.
3. `A05` Queue overflow drops oldest unsent alerts permanently.
4. `O11` No external heartbeat means silent outages can last long.
5. `Q05` Latest-M1-only candidate can miss valid earlier intra-window confirmations.
6. `Q12` M1-only cadence may increase low-confidence alert noise.
7. `D06` No stale-feed detector for MT5 data freeze.
8. `O01` Replay window only 3 M15 bars may be too short for longer outages.

---

## 9) Quick Runbook: What To Check First When You Suspect Failure

1. Check `logs/bot.log` for:
   - `startup failed`
   - `symbol processing error`
   - `mt5 reconnect attempt`
   - `signal blocked by dedup`
   - `telegram send failed`
2. Verify bot mode is not dry-run.
3. Verify MT5 terminal is open, logged in, and symbols/timeframes have history loaded.
4. Verify `.env` secrets and `config/settings.yaml` alias mappings.
5. Check `data/failed_signals.json` size and age of queued items.
6. Check `data/dedup_state.json` exists and is writable.
7. Confirm host clock is synced (UTC) and machine was not sleeping/down.

---

## 10) Source Basis (Code + Docs Reviewed)

- `src/trading_signal_bot/main.py`
- `src/trading_signal_bot/strategy.py`
- `src/trading_signal_bot/mt5_client.py`
- `src/trading_signal_bot/telegram_notifier.py`
- `src/trading_signal_bot/repositories/dedup_store.py`
- `src/trading_signal_bot/settings.py`
- `src/trading_signal_bot/utils.py`
- `config/settings.yaml`
- `docs/PRD.md`
- `docs/Planning.md`
- `docs/ARCHITECTURE.md`
- `docs/TECHNICAL_SPEC.md`
