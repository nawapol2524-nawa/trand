# TLS SECURITY HARDENING AUDIT

## 1. Root Cause & Insecure Behavior
The `CTraderMCPBroker` had an insecure fallback loop in `_urlopen`. If the system lacked CA certificates (resulting in `urllib.error.URLError: CERTIFICATE_VERIFY_FAILED`), it silently bypassed TLS verification by setting `check_hostname = False` and `verify_mode = ssl.CERT_NONE`. This prevented container crashes on environments without configured CA trust stores but opened the broker connection to Man-In-The-Middle (MITM) attacks.

## 2. Exact Fix
- **Removed the insecure fallback logic**: The `try/except` block catching `CERTIFICATE_VERIFY_FAILED` and generating a `CERT_NONE` context was fully excised from `src/brokers/ctrader_mcp.py`.
- **Docker CA Requirement**: Fixed the root cause of the verification failure in production by adding `ca-certificates` to the `apt-get install` directives in the `Dockerfile`. This ensures the Railway container has a populated and up-to-date CA trust store.

## 3. CA Certificate Status
- **Railway/Docker Layer**: Patched and updated.
- **TLS Verification**: Enforced entirely across the application. `check_hostname` and `verify_mode` will use system defaults, throwing a fatal crash rather than bypassing security if intercepted.

## 4. 404 Regression Check
The `tools/call` recovery block (which intercepts `HTTP 404/400`) was tested carefully to ensure it hasn't been disturbed. The HTTP errors propagate as `urllib.error.HTTPError`, which inherits from `URLError`, and is appropriately caught in `call_tool`. The automated regression tests assert that the 404 reconnect handles successfully.

## 5. Security Scan & Test Results
- **Remaining `CERT_NONE` or `check_hostname=False`**: `0` in production code. (Only present as strings in the regression tests asserting their absence).
- **Hardcoded Secrets**: `0` found.
- **Pytest**: `92/92` Passed.
- **Compileall**: Passed (0 syntax errors).

## 6. Strategy / Risk / AI Unchanged
| Component | Changed Files | Lines Changed |
|-----------|---------------|---------------|
| Strategy  | 0             | 0             |
| Risk      | 0             | 0             |
| AI        | 0             | 0             |

No logic, parameters, thresholds, or decision trees were modified.

## 7. Remaining Limitations
None identified within the scope of TLS transport security. The connection to the broker is now exclusively verified HTTPS.
