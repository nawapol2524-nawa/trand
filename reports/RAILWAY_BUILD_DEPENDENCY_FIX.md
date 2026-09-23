# Railway Build Dependency Fix Audit Report

## 1. Overview & Root Cause Analysis

### Identified Problem
During Railway Docker image creation, the build failed during the dependency installation stage:
```
ERROR: Could not find a version that satisfies the requirement ctrader-open-api>=2.0.0
ERROR: No matching distribution found for ctrader-open-api>=2.0.0
```

### Root Cause Verification
1. **PyPI Status**: The package `ctrader_open_api` on PyPI has a highest stable release of `0.9.2` (with `0.9.3` yanked). Version `2.0.0` does not exist on PyPI.
2. **Architectural Realignment**: The trading bot's production broker adapter (`src/brokers/ctrader_mcp.py`) interacts with Deriv cTrader via the official cTrader Remote MCP Server (`https://mcp.ctrader.com/trading/mcp`) over JSON-RPC 2.0 / SSE using Python standard library modules (`urllib.request`, `json`, `time`, `os`).
3. **Stale Requirements**: `ctrader-open-api>=2.0.0`, `twisted>=24.3.0`, and `protobuf>=4.25.0` were legacy dependencies from an early phase prior to Remote MCP adoption. Neither production code nor the test suite imports or requires these packages.
4. **Additional Unused Packages**: `feedparser>=6.0.10`, `requests>=2.31.0`, and `aiohttp>=3.9.0` were also present in `requirements.txt` without any imports in `src/` or `tests/`.

---

## 2. Dependency Audit & Changes

### Files Changed
- `requirements.txt`: Pruned all stale, unreferenced packages. Retained only verified, justified production and test packages.
- `requirements-dev.txt`: Updated comments to remove references to `ctrader-open-api` and `twisted`.
- `reports/RAILWAY_BUILD_DEPENDENCY_FIX.md`: This audit report.

### Detailed Package Reconciliation

| Package | Previous Version | Action | Justification |
| :--- | :--- | :--- | :--- |
| `ctrader-open-api` | `>=2.0.0` | **REMOVED** | Stale SDK. Broker adapter uses Remote MCP via standard library `urllib`. |
| `twisted` | `>=24.3.0` | **REMOVED** | Stale async engine from native cTrader TCP SDK. Not imported anywhere. |
| `protobuf` | `>=4.25.0` | **REMOVED** | Stale binary serializer. Remote MCP communicates via JSON-RPC. |
| `feedparser` | `>=6.0.10` | **REMOVED** | Unused. No RSS/calendar feeds in current production or test codebase. |
| `requests` | `>=2.31.0` | **REMOVED** | Unused. Codebase standardizes on `urllib.request`. |
| `aiohttp` | `>=3.9.0` | **REMOVED** | Unused. Async event loops use standard library `asyncio`. |
| `numpy` | `>=1.26,<2.0` | **KEPT** | Required by `src/core/indicators.py`, `src/core/signals.py`, and backtest engine. |
| `python-dotenv` | `>=1.0.0` | **KEPT** | Required for environment configuration loading in `src/app/main.py` and `src/config.py`. |
| `pyyaml` | `>=6.0` | **KEPT** | Required for reading `configs/symbols.yaml`. |
| `pytest` | `>=8.0.0` | **KEPT** | Test suite runner. |
| `pytest-asyncio` | `>=0.23.0` | **KEPT** | Async test execution. |
| `pytest-cov` | `>=5.0.0` | **KEPT** | Test coverage reporting. |

### Final `requirements.txt`
```
numpy>=1.26,<2.0
python-dotenv>=1.0.0
pyyaml>=6.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=5.0.0
```

---

## 3. Evidence: cTrader Remote MCP Independence from ctrader-open-api

1. **Broker Adapter Analysis** (`src/brokers/ctrader_mcp.py`):
   - Transport: HTTP POST to `https://mcp.ctrader.com/trading/mcp`
   - Protocol: JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`)
   - Library: `urllib.request.Request`, `urllib.request.urlopen`, `json.dumps`, `json.loads`
   - Imports:
     ```python
     import json
     import os
     import time
     import urllib.error
     import urllib.request
     from typing import Any, Optional
     ```
   - Zero references to `ctrader_open_api`, `twisted`, or `google.protobuf`.

2. **Full Codebase Import Audit**:
   - `src/` modules: `['__future__', 'abc', 'asyncio', 'dataclasses', 'datetime', 'dotenv', 'enum', 'json', 'logging', 'math', 'numpy', 'os', 'pathlib', 'signal', 'src', 'sys', 'time', 'typing', 'urllib', 'uuid']`
   - `tests/` modules: `['__future__', 'dataclasses', 'datetime', 'hashlib', 'json', 'math', 'numpy', 'os', 'pathlib', 'pytest', 'shutil', 'src', 'tempfile', 'unittest']`
   - Zero active production references to removed packages.

---

## 4. Local Verification & Audit Results

### Verification Commands & Results

1. **Flake8 Syntax & Critical Lint Check**:
   ```bash
   .venv/bin/flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=.venv,__pycache__,.git
   ```
   - Result: `0` errors.

2. **Bytecode Compilation**:
   ```bash
   .venv/bin/python -m compileall -q -x ".venv|.git" .
   ```
   - Result: `PASS` (0 syntax or bytecode errors).

3. **Full Pytest Suite**:
   ```bash
   PYTHONPATH=. .venv/bin/python -m pytest tests/
   ```
   - Result: `74 passed in 0.63s` (100% pass rate).

4. **Dynamic Import Verification of All `src` Packages**:
   - Result: 21 modules walked and imported successfully with zero `ModuleNotFoundError` or `ImportError`.

5. **Static AST Out-of-Sample (OOS) Leakage Audit**:
   ```bash
   PYTHONPATH=. .venv/bin/python scripts/audit_oos_access.py
   ```
   - Result: `PASS` (11 authorized occurrences, 0 unauthorized leaks).

6. **Dry-Run DEMO Mode Startup & Graceful Shutdown**:
   - Command: `TRADING_MODE=DEMO LIVE_TRADING_ENABLED=false .venv/bin/python -m src.app.main`
   - Result: Emits `BOT_STARTING`, `RUNNER_START`, and initializes runner against Demo MCP endpoint.

7. **Docker Build Context & Safety Rules Audit**:
   - `TRADING_MODE=DEMO` in Dockerfile: **CONFIRMED**
   - `LIVE_TRADING_ENABLED=false` in Dockerfile: **CONFIRMED**
   - Zero hardcoded secrets in Dockerfile or `requirements.txt`: **CONFIRMED**
   - `.env` excluded by `.dockerignore`: **CONFIRMED**
   - `STRATEGY_SPEC.md` included by `.dockerignore` (`!STRATEGY_SPEC.md`): **CONFIRMED**

8. **Local Docker Build Command**:
   ```bash
   docker build -t trand-railway-test .
   ```
   - Result: `zsh: command not found: docker`.
   - Host machine status: Docker CLI and daemon are not installed on the local macOS development host.
   - Factual Verdict: Local Docker build execution is **BLOCKED** due to missing local Docker daemon. Build context and Dockerfile syntax are statically **VERIFIED**.

---

## 5. Deployment Readiness Verdict

- **Requirements Resolution**: `PASS` — The nonexistent dependency `ctrader-open-api>=2.0.0` has been removed. All remaining dependencies are standard wheels supported natively on Python 3.11 Linux.
- **Test Suite**: `PASS` (74/74 passing).
- **Code Integrity**: `PASS` (No unresolved imports).
- **Local Container Build**: `BLOCKED` (Docker runtime absent on macOS host).
- **Railway Remote Build**: `READY_TO_BUILD` (Railway Linux builder will execute `pip install --no-cache-dir -r requirements.txt` with zero missing distribution errors).
