# Project Milestones

This file defines execution order and done criteria.

## Priority Order
1. Finish V1 in production-quality operation.
2. Build V2 backtester (time-based first, then SL/TP).
3. Start V3+ backlog only after V1 + V2 are stable.

## V1 Finalization (Current Priority)

### V1 Done Criteria
- [ ] Bot runs continuously on AWS Windows VPS during required market hours.
- [ ] MT5 connection + symbol alias checks pass at startup.
- [ ] Telegram startup check passes and messages are delivered.
- [ ] No duplicate alerts across restarts (dedup state works).
- [ ] Startup replay catches missed windows without look-ahead behavior.
- [ ] First 50 live/demo alerts manually validated against chart conditions.
- [ ] Logs are monitored daily and no unresolved recurring runtime errors remain.

### V1 Execution Checklist
1. Provision AWS VPS
- [ ] Follow `docs/AWS_VPS_SETUP.md` (Lightsail first, EC2 optional).
- [ ] Restrict RDP (`3389`) to your public IP.
- [ ] Configure AWS budget alerts.

2. Install and configure bot on VPS
- [ ] Install MT5 and login.
- [ ] Install Python + Poetry and project dependencies.
- [ ] Configure `.env` and `config/settings.yaml`.

3. Validate runtime
- [ ] Run dry-run successfully.
- [ ] Run live on demo session.
- [ ] Confirm Telegram startup message.
- [ ] Confirm logs written to `logs/bot.log`.

4. Hardening
- [ ] Install as Windows service (`scripts/install_service.ps1`).
- [ ] Verify service restarts cleanly after reboot.
- [ ] Verify dedup + replay behavior after forced restart.

5. Trading-quality validation
- [ ] Validate first 50 alerts manually.
- [ ] Record mismatches/issues and fix before moving to V2.

## V2 Scope (After V1 Is Fully Done)

### Phase A: Time-Based Backtest
- [ ] Historical loader (M15 + M1).
- [ ] Engine that reuses v1 strategy logic.
- [ ] N-bars outcome model and report output.
- [ ] Rank symbols/scenarios by signal quality.

### Phase B: SL/TP Backtest
- [ ] Add SL/TP exit model (fixed/ATR-based).
- [ ] Compare SL/TP outcomes on top candidates from Phase A.
- [ ] Use results for go/no-go decision.

## V3+ Backlog (Do Not Start Yet)
- Parameter optimization.
- Health monitoring/alerts.
- Optional auto-execution.
- Multi-chat routing.
