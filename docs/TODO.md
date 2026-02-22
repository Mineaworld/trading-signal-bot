# Pre-Deploy Hardening

## Critical
- [x] 1a. Interruptible sleep in failure paths (main.py:232,268)
- [x] 1b. SQLite connection leak (signal_journal.py)
- [x] 1c. Risk field None crash (telegram_notifier.py:269-283)
- [x] 1d. Deploy rollback detached HEAD (deploy.ps1)

## Important
- [x] 2a. MT5_LOGIN validation (settings.py:447)
- [x] 2b. Timezone validation (settings.py)
- [x] 2c. Log level validation (settings.py)
- [x] 2d. Preflight NSSM + service check (preflight_prod.ps1)
- [x] 2e. Remove continue-on-error from Windows CI (ci.yml:70)
- [x] 2f. Resolve relative file paths (settings.py)
- [x] 2g. DedupStore timezone-safe parsing (dedup_store.py)
- [x] 2h. DedupStore persist error handling (dedup_store.py)

## Low
- [x] 3a. Session window time format validation (settings.py)
- [x] 3b. Stochastic zone 0-100 range check (settings.py)
- [x] 3c. fsync before os.replace (utils.py)
- [x] 3d. CI run all tests (ci.yml)
- [x] 3e. Signal journal tests (test_signal_journal.py)
- [x] 3f. Pending setups note (main.py)
