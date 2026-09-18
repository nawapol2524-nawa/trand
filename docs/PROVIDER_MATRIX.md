# Provider Matrix & Interface Verification

| Provider | Purpose | Authentication | Historical Data | Realtime Data | News / Calendar | Rate Limits | Status | Adapter Module |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Deriv.com** | Primary Forex Execution & Ticks | OAuth/API Token (`DERIV_API_TOKEN`) | Yes (M1 ticks/candles via Parquet/WS) | Yes (WebSocket Tick Stream) | No | 100 req/min | **VERIFIED ACTIVE** | `ai_forex_bot.execution.deriv_client` |
| **MetaApi** | MT5 Cent Account Execution | Bearer JWT Token (`METAAPI_TOKEN`) | Yes (MT5 history) | Yes (RPC Stream) | No | Tiered Cloud limits | **CONFIGURED** | `ai_forex_bot.execution.metaapi_client` |
| **ForexFactory**| Economic Calendar & Red Folder | Public Web Scraping (Clean parse) | Yes (Archival) | Yes (Live Calendar Polling) | Yes (CPI/NFP/Interest Rate) | 30 req/min respectful cache | **VERIFIED ACTIVE** | `ai_forex_bot.data.economic.calendar` |
| **GroqCloud** | Fast LLM Sentiment Context | API Key (`GROQ_API_KEY`) | N/A (Stateless) | Yes (<800ms inference) | Yes (NLP reasoning) | 30 req/min free tier | **VERIFIED ACTIVE** | `ai_forex_bot.news_ai.groq_adapter` |
| **Alpha Vantage**| Historical Macro News & Sentiment | API Key (`ALPHA_VANTAGE_KEY`) | Yes | Yes | Yes | 5 req/min (Free) | **CONFIGURED** | `ai_forex_bot.data.news.alpha_vantage` |
| **OpenAI** | Advanced Synthesis & Reasoning | API Key (`OPENAI_API_KEY`) | N/A | Yes | Yes | Tier-dependent | **CONFIGURED** | `ai_forex_bot.news_ai.openai_adapter` |
| **LINE Notify** | Operator Alerts | Bearer Token (`LINE_CHANNEL_ACCESS_TOKEN`) | N/A | Yes (Push Notifications)| No | 1000 msg/hr | **VERIFIED ACTIVE** | `ai_forex_bot.monitoring.notifier` |
