# Security Policy & Safeguards

## 1. Secret Management Policy
1. **Never Commit Secrets:** `.env` is explicitly ignored in `.gitignore`.
2. **Never Log Secrets:** Logging filters sanitize all outgoing string buffers, ensuring tokens and passwords never enter log streams or terminal outputs.
3. **No Credential Access to AI Models:** AI Models and prompt builders receive sanitized numerical and contextual strings only. Under no circumstances are API tokens passed into LLM contexts.

## 2. Execution Safeguards
1. **Air-Gapped Sandbox for Training:** Training pipelines run in pure offline mode on local Parquet files without external broker execution privileges.
2. **Read-Only Data Ingestion:** Historical Parquet files in `data/market/raw/` are opened read-only; downstream pipelines write to distinct staging folders (`clean/`, `features/`, `labels/`).
3. **Emergency Disconnect:** Immediate process death and state dump if authentication fails or unexpected payloads are received from WebSocket channels.
