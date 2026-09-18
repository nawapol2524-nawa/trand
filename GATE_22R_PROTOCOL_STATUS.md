# GATE 22R — OFFICIAL PROTOCOL STATUS & BENCHMARK CLASSIFICATION
**Authority:** Institutional Quantitative Systems Audit & Software Quality Engineering  
**Effective Date:** 2026-09-18  
**Governing Standard:** Empirical Zero-Leakage & Cryptographic OOS Access Control  

---

## 1. System & Protocol State Declaration

The quantitative system formally registers the following binding protocol states:

```yaml
system_states:
  GATE_22: CONSUMED_CONTAMINATED
  GATE_22R: RESEARCH_PROTOCOL_REPAIR
  OLD_TEST: CONTAMINATED_HISTORICAL_DIAGNOSTIC_SET
  NEW_OOS: WAITING_FOR_REAL_POST_BOUNDARY_DATA
  LIVE_TRADING: false
```

> [!CAUTION]
> **PROHIBITION OF "FROZEN TEST" TERMINOLOGY:**  
> The historical data partition spanning **2026-07-27 09:45:00 UTC to 2026-09-18 02:00:00 UTC** (`frxEURUSD` M15 rows `20565:24194`, 3,630 bars) is **NEVER** to be referred to as an "unseen holdout", "out-of-sample test", or "frozen test" in any quantitative capacity. It is classified permanently as **`CONTAMINATED_HISTORICAL_DIAGNOSTIC_SET`**.

---

## 2. Forensic Reconstruction of Protocol Breach

During the execution of Gate 22, the historical holdout partition was accessed multiple times in violation of strict blind holdout governance:

1. **Step 1 Leakage (`scripts/research_step1_root_cause.py`):**
   - The test partition (`bounds.test_indices`) was directly ingested to evaluate why 0 trades occurred in Gate 21.
   - Calibrated probability distributions ($P(\text{HOLD}), P(\text{BUY}), P(\text{SELL})$) and bar-by-bar signal traces were generated on the holdout partition.
   - Produced artifacts: `GATE_22_SIGNAL_TRACE.csv`, `GATE_22_PROBABILITY_DISTRIBUTION.csv`.

2. **Step 2 Leakage (`scripts/research_step2_score_analysis.py`):**
   - Model predictions on the holdout partition were sorted into percentile tiers (Top 0.5% to Top 20%).
   - Realized gross returns, transaction costs, net returns, MAE, and MFE were calculated directly against holdout labels.
   - Produced artifact: `GATE_22_SCORE_BUCKETS.csv`.

3. **Temporal Inversion Prior to Candidate Research:**
   - Steps 1 and 2 occurred **BEFORE** Step 3 (`scripts/research_step3_model_feature_experiments.py`) and Step 4 (`scripts/research_step4_cross_sectional_analysis.py`) completed model, feature, and hyperparameter research.
   - Consequently, the quantitative researchers had full visibility into the holdout distribution and tail performance prior to formal candidate definition.

4. **Falsified Single-Evaluation Claim:**
   - The original report (`GATE_22_MODEL_RESEARCH_REPORT.md`) claimed the test set was "evaluated exactly once at the conclusion of research." Execution audit proves the holdout partition was read and processed in at least three separate scripts (`scripts/research_step1_root_cause.py`, `scripts/research_step2_score_analysis.py`, and `scripts/research_step5_frozen_test_evaluation.py`).

---

## 3. Scope of Usability for the Old Test Set

To prevent post-hoc optimization and p-hacking, the usage rights for `OLD_TEST` are strictly bounded:

| Allowed Usage | Status | Justification |
|---|:---:|---|
| **Future Model Selection** | ❌ **PROHIBITED** | Information leakage from prior exposure invalidates statistical independence. |
| **Feature Selection / Removal** | ❌ **PROHIBITED** | Tail return visibility biases feature pruning. |
| **Threshold / Hyperparameter Tuning** | ❌ **PROHIBITED** | Knowing $P(\text{BUY})$ distribution invites threshold overfitting. |
| **Strategy Promotion Benchmark** | ❌ **PROHIBITED** | Cannot act as proof of generalization. |
| **Historical Forensic Diagnostics** | ✅ **PERMITTED** | Retained strictly to understand regime effects, calibration compression, and execution barriers during the summer 2026 regime. |

---

## 4. Policy for Future Out-of-Sample (New OOS) Validation

1. **Strict Chronological Boundary:**
   Any future out-of-sample benchmark (`NEW_OOS`) must consist exclusively of real market data generated chronologically **after** `2026-09-18 03:15:00 UTC`.
2. **Zero Fabrication:**
   Synthetic candles, resampled data, or simulated price paths are strictly prohibited from serving as OOS holdouts.
3. **Current Data Boundary Status:**
   As of current repository ingestion, the maximum available epoch across all clean parquets is `2026-09-18 03:15:00 UTC`. Therefore:
   $$\text{NEW\_OOS\_STATUS} = \mathbf{WAITING\_FOR\_REAL\_POST\_BOUNDARY\_DATA}$$
4. **Mandatory Cryptographic Locking:**
   Access to future OOS data requires automated enforcement via `ai_forex_bot/data/oos_guard.py` with signed manifests, SHA-256 code/data pinning, and one-time evaluation tokens.
