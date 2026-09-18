# Execution Engine & Broker Abstraction

## 1. Decoupled Broker Architecture
The execution layer implements an abstract `BaseBroker` contract:
- `connect()`, `disconnect()`, `health_check()`
- `get_account_state()`, `get_quote()`
- `place_order()`, `close_position()`
- `reconcile()`

Available Implementations:
- **`SimulatedBroker`:** Offline backtesting and paper trading with exact spread, slippage, and margin simulation.
- **`DerivWebSocketClient`:** Live institutional streaming and execution on Deriv.com.

## 2. Order Lifecycle State Machine
```text
SIGNAL_RECEIVED ➔ RISK_APPROVED ➔ ORDER_SUBMITTED ➔ BROKER_ACKNOWLEDGED ➔ FILLED ➔ CLOSED
        │                │
        ▼                ▼
   RISK_REJECTED      REJECTED / CANCELLED
```
Reconciliation loops continuously synchronize internal position records against broker account ledgers to resolve disconnects and partial fills safely.
