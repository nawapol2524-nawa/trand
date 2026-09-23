# AI Cost Control & Token Optimization
**Version**: 1.0.0 (Phase N Standard)  
**Status**: APPROVED

---

## 1. Principles of Cost Minimization

1. **Zero Per-Tick Calls**: The `EventDetector` ensures AI is never called on tick updates or standard un-eventful candles. Calls occur strictly on structural market shifts (BOS, monitored zone entry, regime transition).
2. **Mandatory Cooldown**: A minimum 60-second cooldown is enforced per symbol between AI invocations.
3. **Context Compression**: The system never sends raw historical arrays of candle text to the LLM. All indicators ($RSI, EMA, ATR$) and candlestick patterns are pre-computed deterministically into compact numeric JSON summaries ($< 250$ tokens per prompt).
4. **Targeted Model Selection**:
   * Production target: Lightweight, ultra-cost-efficient models (`gpt-4o-mini`, `llama-3.1-8b-instant`).
   * Never use frontier reasoning models (`o1`, `gpt-4o`) for high-frequency market structure evaluation where latency and cost would be prohibitive.
5. **Backtest Determinism**: Live API calls are strictly forbidden during multi-year historical backtests. Backtests run either in offline rule mode or by replaying stored decision traces from previous sessions.
