# Environment & Secret Inventory

**Audit Policy:** Zero Secret Exposure. Key existence is verified without exposing values.

| Variable Name | Provider | Purpose | Status | Required/Optional | Consuming Module |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `DERIV_API_TOKEN` | Deriv.com | WebSocket trading & live price streaming | PRESENT | REQUIRED (Deriv Broker) | `ai_forex_bot.execution.deriv_client` |
| `DERIV_APP_ID` | Deriv.com | Client application registration ID | PRESENT | REQUIRED (Deriv Broker) | `ai_forex_bot.execution.deriv_client` |
| `ENABLE_DERIV` | Internal | Broker mode toggle (`true`/`false`) | PRESENT | OPTIONAL | `ai_forex_bot.config.settings` |
| `METAAPI_TOKEN` | MetaApi.cloud | Cloud RPC integration for MT5 Cent accounts | PRESENT | OPTIONAL (MT5 Broker) | `ai_forex_bot.execution.metaapi_client` |
| `METAAPI_ACCOUNT_ID` | MetaApi.cloud | Managed MT5 instance account ID | PRESENT | OPTIONAL (MT5 Broker) | `ai_forex_bot.execution.metaapi_client` |
| `TESTNET_API_KEY` | Binance | Crypto testnet API access | PRESENT | OPTIONAL (Crypto Mode) | `ai_forex_bot.execution.binance_client` |
| `TESTNET_SECRET_KEY`| Binance | Crypto testnet HMAC signature secret | PRESENT | OPTIONAL (Crypto Mode) | `ai_forex_bot.execution.binance_client` |
| `GROQ_API_KEY` | GroqCloud | High-speed LLM sentiment analysis (Llama 3) | PRESENT | OPTIONAL (News AI) | `ai_forex_bot.news_ai.llm_analyzer` |
| `OPENAI_API_KEY` | OpenAI | Auxiliary NLP embedding / reasoning | PRESENT | OPTIONAL (News AI) | `ai_forex_bot.news_ai.llm_analyzer` |
| `ALPHA_VANTAGE_KEY`| Alpha Vantage | Macroeconomic news & sentiment feed | PRESENT | OPTIONAL (Macro Data)| `ai_forex_bot.data.news.alpha_vantage` |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE | Operational trade alert messaging | PRESENT | OPTIONAL (Alerting) | `ai_forex_bot.monitoring.notifier` |
| `LINE_USER_ID` | LINE | Target user ID for push alerts | PRESENT | OPTIONAL (Alerting) | `ai_forex_bot.monitoring.notifier` |
| `GDRIVE_WEBHOOK_URL`| Google Apps | Off-site trade ledger and cloud sync | PRESENT | OPTIONAL (Audit) | `ai_forex_bot.monitoring.gdrive_sync` |
| `DASHBOARD_PIN` | Web Terminal | SHA-256 gated PIN authentication | PRESENT | OPTIONAL (Dashboard)| `ai_forex_bot.monitoring.dashboard` |
