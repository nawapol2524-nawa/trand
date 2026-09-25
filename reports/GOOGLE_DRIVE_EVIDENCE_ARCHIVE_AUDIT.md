# Google Drive Trading Evidence Archive — Architecture & Implementation Audit

**Audit Date**: 2026-09-25  
**Target Google Drive Folder ID**: `1pEn5CK-qeXuPQYbbVc6KMNjbjTGwvn5I`  
**Deployment Mode**: DEMO (Live Trading strictly disabled: `LIVE_TRADING_ENABLED=false`)  
**Status**: COMPLETE & VERIFIED  

---

## 1. Executive Summary

This engineering implementation establishes a production-grade, asynchronous **Trading Evidence Archive** for the 24/7 Autonomous Forex Trading Bot. The system continuously collects, organizes, sanitizes, and preserves all critical runtime evidence:

- **Runtime Logs**: Structured JSONL capturing all loop events, broker connections, data acquisitions, signals, decisions, and system exceptions.
- **Decision Traces**: Comprehensive audit records of every AI invocation, context summary, proposal, deterministic gate evaluation, and risk check.
- **Dual Trade Ledger**: Real-time trade tracking saved simultaneously in machine-readable `.jsonl` and human/analyst-friendly `.csv` with authoritative entry/exit prices, volume, commissions, swap, net P&L, and R-multiples.
- **Reconciliation Logs**: Complete state audit records between local bot tracking and cTrader broker positions.
- **Operational Health**: Telemetry snapshots recording heartbeats, broker latency, queue sizes, and Google Drive sync status.
- **Daily Summaries**: Authoritative end-of-day reports summarizing performance, win rate, profit factor, average R-multiple, errors, and upload statistics.

### Zero-Impact Guarantee & Constraints
- **Zero Strategy Changes**: Strategy logic, indicator periods, BOS calculations, candlestick patterns, and thresholds remain 100% frozen.
- **Zero Risk Changes**: Risk model, daily loss limits, consecutive loss halts, and position sizing formulas remain untouched.
- **Zero AI Policy Changes**: Prompting, validation gate, and advisory logic remain unchanged.
- **Decoupled Asynchrony**: The trading cycle **never** awaits Google Drive API calls. All evidence is written locally and durably first (`state/evidence/`). An independent background worker uploads files in batches, applying exponential backoff on failures.
- **Safe Retention**: The cleanup routine strictly purges files older than `LOCAL_EVIDENCE_RETENTION_DAYS` (default 30 days) **only if** their upload status is confirmed as `UPLOADED`. Unsent evidence is **never** deleted.

---

## 2. Directory Hierarchy & Storage Layout

### Local Storage Hierarchy (`state/evidence/`)
```text
state/evidence/
├── upload_queue.json
├── runtime_logs/
│   └── YYYY-MM-DD/
│       └── runtime_YYYY-MM-DD.jsonl
├── decisions/
│   └── YYYY-MM-DD/
│       └── decisions_YYYY-MM-DD.jsonl
├── trades/
│   └── YYYY-MM-DD/
│       ├── trade_ledger_YYYY-MM-DD.jsonl
│       └── trade_ledger_YYYY-MM-DD.csv
├── daily_reports/
│   └── YYYY-MM-DD/
│       └── daily_summary_YYYY-MM-DD.json
├── reconciliation/
│   └── YYYY-MM-DD/
│       └── reconciliation_YYYY-MM-DD.jsonl
└── health/
    └── YYYY-MM-DD/
        └── health_telemetry_YYYY-MM-DD.jsonl
```

### Remote Google Drive Target Hierarchy
Under Root Folder ID: `1pEn5CK-qeXuPQYbbVc6KMNjbjTGwvn5I`
```text
1pEn5CK-qeXuPQYbbVc6KMNjbjTGwvn5I/
└── TradingBot/
    ├── runtime_logs/
    │   └── YYYY-MM-DD/
    ├── decisions/
    │   └── YYYY-MM-DD/
    ├── trades/
    │   └── YYYY-MM-DD/
    ├── daily_reports/
    │   └── YYYY-MM-DD/
    ├── reconciliation/
    │   └── YYYY-MM-DD/
    └── health/
        └── YYYY-MM-DD/
```

---

## 3. Secret Redaction & Security Enforcement

All data passing through `EvidenceCollector` undergoes recursive sanitization via `EvidenceCollector.sanitize()` before being written to disk or enqueued:
- Keys matching `token`, `key`, `secret`, `password`, `auth`, `credential`, `bearer` are immediately replaced with `[REDACTED]`.
- String contents containing `Bearer ` or PEM certificate blocks (`-----BEGIN`) are replaced with `[REDACTED]`.
- No credentials or sensitive tokens can ever leak to local evidence files or Google Drive.

---

## 4. Dual Trade Ledger Specifications

The trade ledger writes atomically to both `.jsonl` and `.csv`.

### CSV Field Structure
1. `trade_id`: Unique UUID correlating the trade with decision traces.
2. `symbol`: EURUSD, GBPUSD, USDJPY, or XAUUSD.
3. `direction`: BUY or SELL.
4. `signal_time_utc`: UTC timestamp of strategy trigger.
5. `order_time_utc`: UTC timestamp of broker order submission.
6. `entry_time_utc`: UTC timestamp of execution.
7. `entry_price`: Execution price.
8. `volume`: Lot volume.
9. `stop_loss`: Absolute SL price.
10. `take_profit`: Absolute TP price.
11. `exit_time_utc`: UTC timestamp when closed.
12. `exit_price`: Close price reported by broker or reconciliation.
13. `close_reason`: TAKE_PROFIT, STOP_LOSS, CLOSED_EXTERNAL, etc.
14. `gross_pnl`: Authoritative broker gross profit/loss.
15. `commission`: Total commission charged.
16. `swap`: Overnight financing cost.
17. `net_pnl`: Final realized net P&L.
18. `risk_amount`: Dollar risk at entry.
19. `R_multiple`: Realized net return expressed as a multiple of risk (`net_pnl / risk_amount`).
20. `order_id`: Broker order identifier.
21. `position_id`: Broker position identifier.
22. `strategy_version`: Identifying strategy algorithm.
23. `bot_git_sha`: Commit SHA running the bot.
24. `ai_decision`: AI proposal decision.
25. `ai_confidence`: AI confidence score.
26. `gate_result`: Deterministic gate verification outcome.
27. `risk_result`: Risk engine approval status.
28. `source`: BOT_EVENT, BROKER_RECONCILIATION, BROKER_HISTORY, or DERIVED.

---

## 5. Asynchronous Uploader & Resiliency Architecture

- **Worker**: `EvidenceUploader` runs in the background as an `asyncio.Task` inside `TradingBotRunner.run_forever()`.
- **Durable Queue**: `upload_queue.json` maintains the state (`PENDING`, `UPLOADING`, `UPLOADED`, `FAILED`), retry count, and timestamps of all local evidence files.
- **Batch Processing**: Configurable via `GDRIVE_BATCH_SIZE` (default: 20 files per cycle).
- **Interval**: Configurable via `GDRIVE_UPLOAD_INTERVAL_SECONDS` (default: 30.0s).
- **Exponential Backoff**: On any network or Drive API error, the worker backs off from 5s up to a maximum of 300s, preventing log flooding and CPU spikes.
- **Retention Guard**: `apply_retention()` runs periodically to clean local storage according to `LOCAL_EVIDENCE_RETENTION_DAYS` (default: 30 days). Files are strictly checked: if status is `PENDING` or `FAILED`, deletion is skipped.

---

## 6. Verification & Test Evidence

### Complete Test Suite Execution
- **Command**: `.venv/bin/pytest tests/ -v`
- **Results**: `109 passed in 4.85s` (100% PASS)
- **Compilation**: `python3 -m compileall -q src tests` exited with code 0 (clean).

### Evidence Archive Unit Tests (`tests/unit/test_evidence_archive.py`)
- `TestEvidenceCollector::test_directory_initialization`: PASS
- `TestEvidenceCollector::test_sanitize_secrets`: PASS
- `TestEvidenceCollector::test_record_runtime_event`: PASS
- `TestEvidenceCollector::test_record_trade_and_update_exit`: PASS
- `TestEvidenceCollector::test_generate_daily_summary`: PASS
- `TestGoogleDriveClient::test_default_config`: PASS
- `TestGoogleDriveClient::test_default_folder_id_fallback`: PASS
- `TestGoogleDriveClient::test_subfolder_creation_and_caching`: PASS
- `TestGoogleDriveClient::test_resolve_folder_path_hierarchy`: PASS
- `TestGoogleDriveClient::test_upload_file_new_and_update`: PASS
- `TestEvidenceUploader::test_uploader_does_not_upload_when_disabled`: PASS
- `TestEvidenceUploader::test_uploader_processes_batch_successfully`: PASS
- `TestEvidenceUploader::test_uploader_exponential_backoff_on_failure`: PASS
- `TestEvidenceUploader::test_retention_policy_preserves_unsent_files`: PASS

---

## 7. Configuration Reference

| Environment Variable | Default Value | Description |
|---|---|---|
| `GOOGLE_DRIVE_ENABLED` | `false` | Master toggle for Google Drive uploading. |
| `GOOGLE_DRIVE_FOLDER_ID` | `1pEn5CK-qeXuPQYbbVc6KMNjbjTGwvn5I` | Root folder ID on Google Drive. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | _None_ | Service Account credentials (raw JSON or base64). |
| `GOOGLE_APPLICATION_CREDENTIALS` | _None_ | File path to Service Account JSON keyfile. |
| `GOOGLE_REFRESH_TOKEN` | _None_ | OAuth2 Refresh Token (alternative auth). |
| `GOOGLE_CLIENT_ID` | _None_ | OAuth2 Client ID. |
| `GOOGLE_CLIENT_SECRET` | _None_ | OAuth2 Client Secret. |
| `GDRIVE_UPLOAD_INTERVAL_SECONDS` | `30.0` | Background upload polling interval. |
| `GDRIVE_BATCH_SIZE` | `20` | Max files processed per upload batch. |
| `LOCAL_EVIDENCE_RETENTION_DAYS` | `30` | Days to retain uploaded evidence files locally. |
| `STATE_DIR` | `./state` | Root directory for state and local evidence storage. |
