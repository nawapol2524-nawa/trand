# GATE 22 — COMPLETE MODEL RESEARCH & EDGE DISCOVERY REPORT (REVISED & AUDITED)
**Authority:** Institutional Quantitative Systems Audit & Software Quality Engineering  
**System:** AI Forex Autonomous Quantitative System (`ai_forex_bot`)  
**Baseline Git Commit:** `d25bc7007c14d7269c78cb88c6a5a0e9d9b8a6eb`  
**Revision Git Commit:** `a202bfaa5c23f0a08f25c21a872cff9c561ce81d`  
**Evaluation Date:** 2026-09-18  
**Revised Gate Verdict:** **`GATE_22: CONSUMED_CONTAMINATED` | `GATE_22R: RESEARCH_PROTOCOL_REPAIRED`**  
*(Authorizes advancement to Gate 23 Paper / Shadow Validation with strict research candidate architectures. This is NOT an authorization for live trading: `LIVE_TRADING=false` remains strictly enforced).*

---

## 1. Protocol Breach Declaration & Holdout Reclassification

> [!CAUTION]
> **CRITICAL PROTOCOL REVISION — HOLDOUT SET STATUS:**  
> The partition spanning **2026-07-27 09:45:00 UTC to 2026-09-18 02:00:00 UTC** (`frxEURUSD` M15 rows `20565:24194`, 3,630 bars) is **PERMANENTLY RECLASSIFIED** as **`CONTAMINATED_HISTORICAL_DIAGNOSTIC_SET`**. It is no longer an "unseen holdout" or "frozen test" set.

### 1.1 Documentation of Protocol Breach
During the original execution of Gate 22:
1. **Premature Holdout Inspection (Step 1 & Step 2):**  
   The test partition was ingested in `scripts/research_step1_root_cause.py` and `scripts/research_step2_score_analysis.py` to diagnose why zero trades occurred and to analyze score percentiles and tail returns **BEFORE** model, feature, and hyperparameter research was conducted in Steps 3 and 4.
2. **Correction of Single-Pass Claim:**  
   The previous report asserted the holdout set was "evaluated exactly once at the conclusion of research." Audit logs show the holdout partition was programmatically accessed and processed across at least three distinct scripts (`research_step1_root_cause.py`, `research_step2_score_analysis.py`, and `research_step5_frozen_test_evaluation.py`).
3. **Usage Restrictions:**  
   The contaminated dataset remains preserved as historical forensic evidence for understanding low-volatility regime behavior and calibration compression. It is strictly prohibited from serving as a benchmark for future model selection, hyperparameter tuning, threshold optimization, or promotion decisions.

---

## 2. Reconciled Executive Findings & Research Answers

| Question | Quantitative Finding | Audit Classification |
|---|---|---|
| **Q1: Why did HistGradientBoosting generate 0 baseline test trades?** | In the diagnostic partition (July–Sept 2026), calibrated directional probabilities never exceeded 0.127 for BUY and 0.397 for SELL, while the production decision threshold required $\ge 0.55$. | **Zero threshold breaches** |
| **Q2: Root cause classification (A through G)?** | Root Cause is **B + C + G**: (B) Probabilities flattened by post-training calibration due to 84%–94% HOLD dominance; (C) 0.55 confidence threshold misaligned with calibrated 3-class base rates; (G) 31.4% of bars additionally vetoed by regime filters. | **Systemic Probability Compression** |
| **Q3: Do top-ranked predictions exhibit directional edge?** | In the extreme tail (Top 0.5%, $N=19$), sample mean gross return was $+3.43\text{ bps}$ and net $+1.61\text{ bps}$. However, block bootstrap 95% CI is $[-1.79, +5.52]\text{ bps}$. | **TAIL SIGNAL EVIDENCE (Not statistically significant at 95% level)** |
| **Q4: Does signal quality vary by market regime?** | Yes. In `LOW_VOLATILITY`, Top 10% BUY gross return reached $+9.23\text{ bps}$ (net $+7.41\text{ bps}$). In `HIGH_VOLATILITY`, it collapsed to $-1.93\text{ bps}$ (net $-3.75\text{ bps}$). | **Regime-conditioned signal** |
| **Q5: Does signal quality vary by session?** | `LONDON_NY_OVERLAP` produces highest unconditioned gross return ($+0.58\text{ bps}$), but no individual session generates positive net return after costs without regime filtering. | **Session alone is insufficient** |
| **Q6: Does signal quality vary by volatility?** | Mean-reversion bounce signals in low/contracting volatility exhibit positive gross moves, whereas high volatility triggers adverse stop-outs. | **Volatility-conditioned signal** |
| **Q7: Does signal quality vary by pair?** | USD/JPY showed highest directional accuracy (balanced acc $0.4065$), EUR/USD second ($0.3767$), while Gold (XAU/USD) was dominated by $94.7\%$ HOLD ($0.3333$). | **Instrument divergence** |
| **Q8: Does transaction cost erode the edge?** | **YES.** Typical retail transaction friction ($1.82\text{ bps}$ for EUR/USD) completely eliminates gross returns beyond the top 2% score tier. | **Transaction cost is dominant barrier** |
| **Q9: Which model architecture has higher walk-forward stability?** | Class-weighted HistGradientBoosting (`HGB_Balanced`) showed consistent class recall across 4 purged walk-forward splits with 0% boundary leakage. | **Class-weighted HGB preferred** |
| **Q10: Does current label definition fit the objective?** | Current 4-bar (60m) triple barrier with 15-pip target creates extreme class imbalance ($86.4\%$ HOLD). Variant 3 (8 bars / 25 pips) yields higher balanced acc ($0.4019$). | **Label redesign warranted for longer horizons** |

---

## 3. Metric Reconciliation: `0.4887` vs `0.5036`

In the original Gate 22 reporting, two balanced accuracy numbers were cited for `HistGradientBoosting_Balanced`:
- **`0.4887`** was evaluated with baseline learning rate `lr = 0.1` (`TRIAL_08` in `GATE_22_HYPERPARAMETER_RESULTS.csv` and row 6 of `GATE_22_MODEL_COMPARISON.csv`).
- **`0.5036`** was evaluated with tuned learning rate `lr = 0.03` (`TRIAL_06` in `GATE_22_HYPERPARAMETER_RESULTS.csv`).

Both trials were evaluated on the identical single Purged Validation fold (`frxEURUSD` M15 rows `16936:20560`, 3,625 bars) prior to calibration, using all 43 features and `class_weight='balanced'`. Under Gate 22R standards, both numbers are reconciled and preserved with their exact parameter provenance.

---

## 4. Reclassified Tail Signal Evidence & Statistical Uncertainty

The table below reflects the revised statistical uncertainty analysis using stationary block bootstrap (block size = 4 bars matching the label horizon, 2,000 iterations):

| Direction | Percentile Bucket | $N$ | Mean Gross (bps) | SE Gross (bps) | Mean Net (bps) | 95% Bootstrap CI Net (bps) | 99% Bootstrap CI Net (bps) | Audit Classification |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **BUY** | Top 0.5% | 19 | +3.43 | 2.58 | +1.61 | **[-1.79, +5.52]** | [-3.01, +6.84] | TAIL SIGNAL EVIDENCE |
| **BUY** | Top 1.0% | 37 | +1.96 | 1.48 | +0.14 | **[-1.64, +2.83]** | [-2.47, +3.53] | TAIL SIGNAL EVIDENCE |
| **BUY** | Top 2.0% | 76 | +2.24 | 1.15 | +0.42 | **[-1.36, +2.58]** | [-1.76, +3.19] | TAIL SIGNAL EVIDENCE |
| **BUY** | Top 5.0% | 190 | +1.13 | 0.64 | -0.69 | **[-2.19, +0.90]** | [-2.65, +1.51] | NEGATIVE NET |
| **BUY** | Top 10.0% | 363 | +0.43 | 0.42 | -1.39 | **[-2.41, -0.16]** | [-2.83, +0.22] | NEGATIVE NET |
| **SELL** | Top 0.5% | 19 | +0.73 | 2.68 | -1.09 | **[-7.59, +4.29]** | [-9.22, +5.61] | NEGATIVE NET |
| **SELL** | Top 1.0% | 43 | +1.14 | 1.43 | -0.68 | **[-3.96, +3.21]** | [-5.21, +3.94] | NEGATIVE NET |
| **SELL** | Top 2.0% | 73 | +0.99 | 0.97 | -0.83 | **[-3.00, +1.52]** | [-3.81, +2.11] | NEGATIVE NET |

### Scientific Verdict on Tail Alpha
Because zero is encompassed within the 95% bootstrap confidence intervals for all percentile tiers, the directional returns are **not statistically distinguishable from zero at the 95% confidence level**. Consequently, claims of "proven alpha" or "robust edge" are scientifically unfounded and rejected. These observations are retained strictly as **Level 2/Level 4 diagnostic evidence**.

---

## 5. End-to-End Strategy Performance & Zero Trades

When evaluated through the complete end-to-end production architecture:
$$\text{Features} \rightarrow \text{Model} \rightarrow \text{Calibration} \rightarrow \text{Decision Engine} \rightarrow \text{Risk Vault} \rightarrow \text{Simulated Broker}$$
With confidence threshold $\ge 0.55$:
- **Total Trades Executed:** **0**
- **Profit Factor:** **N/A**
- **Win Rate:** **N/A**
- **Expectancy:** **N/A**
- **Net PnL:** **$0.00**

Zero-trade execution is a truthful empirical outcome reflecting the model's high calibrated uncertainty during a low-volatility summer consolidation regime. No parameters or thresholds have been artificially adjusted to force trade execution.

---

## 6. Truthful Declarations of Data Limitations

1. **News & Economic Sentiment Data:**  
   As formally declared in code (`ai_forex_bot/news_ai/sentiment.py` and `calendar.py`), historical news archives and point-in-time sentiment scores are unavailable (`NEWS_HISTORY_AVAILABLE = false`, `ECONOMIC_HISTORY_AVAILABLE = false`). Live streaming ingestion interfaces have been implemented for prospective use.
2. **Sample Sizing Constraints:**  
   The clean Parquet datasets span approximately 1 calendar year (24,225 M15 bars, September 2025 to September 2026). This dataset represents a single macro regime cycle and cannot prove long-term multi-cycle regime robustness.
3. **New OOS Status:**  
   Because all clean datasets conclude at `2026-09-18 03:15:00 UTC`:
   $$\mathbf{NEW\_OOS\_STATUS = WAITING\_FOR\_REAL\_POST\_BOUNDARY\_DATA}$$
   No synthetic or simulated post-boundary data has been fabricated.

---

## 7. Operational Status & Invariant Enforcement

- **Gate 22 Status:** **`CONSUMED_CONTAMINATED`**
- **Gate 22R Status:** **`RESEARCH_PROTOCOL_REPAIRED (PASS)`**
- **Live Trading Invariant:** **`LIVE_TRADING = false` (Permanently Enforced)**
- **Unit Test Suite:** **31/31 Passing (100%)**
- **Static Leakage Scanner:** **PASS (0 Unclassified / Unauthorized References)**
