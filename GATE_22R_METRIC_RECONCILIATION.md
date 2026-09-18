# GATE 22R — METRIC RECONCILIATION AUDIT: `0.4887` vs `0.5036`
**Authority:** Institutional Quantitative Systems Audit & Software Quality Engineering  
**Subject:** Reconciliation of Discrepancy in `HistGradientBoosting_Balanced` Accuracy Reporting  
**Status:** **RESOLVED & RECONCILED**  

---

## 1. Executive Summary & Root Cause

During Gate 22, two conflicting balanced accuracy values were reported for the class-weighted HistGradientBoosting model:
- `GATE_22_MODEL_COMPARISON.csv`: **`0.4887`**
- `GATE_22_MODEL_RESEARCH_REPORT.md` / `GATE_22_FINAL_TEST_RESULTS.csv` / Git Commit `a202bfa`: **`0.5036`**

Forensic code audit of `scripts/research_step3_model_feature_experiments.py` revealed that both numbers are legitimate empirical measurements from the research pipeline, but they correspond to **two different hyperparameter trials**:
1. **`0.4887`** is the baseline model comparison score evaluated with standard learning rate `lr = 0.1` (`TRIAL_08` in `GATE_22_HYPERPARAMETER_RESULTS.csv`).
2. **`0.5036`** is the tuned score from hyperparameter grid search evaluated with learning rate `lr = 0.03` (`TRIAL_06` in `GATE_22_HYPERPARAMETER_RESULTS.csv`).

The discrepancy arose because the master text report and Candidate B specification cited the peak tuned result (`0.5036`), while the default model comparison table cited the un-tuned baseline (`0.4887`), without explicitly documenting the change in learning rate between tables.

---

## 2. Systematic Forensic Reconciliation Matrix

| Audit Item | Question | Empirical Finding & Evidence |
|---|---|---|
| **1** | Which experiment did `0.4887` come from? | **Default Model Benchmark** in `scripts/research_step3_model_feature_experiments.py` (Line 126). Model: `HistGradientBoostingModel({"random_state": 42, "class_weight": "balanced"})` with default `learning_rate=0.1`. Corresponds to `TRIAL_08` in `GATE_22_HYPERPARAMETER_RESULTS.csv`. |
| **2** | Which experiment did `0.5036` come from? | **Hyperparameter Grid Search** in `scripts/research_step3_model_feature_experiments.py` (Line 185). Trial: `TRIAL_06` with `learning_rate=0.03`, `max_iter=100`, `min_samples_leaf=20`, `l2_regularization=0.0`, `class_weight='balanced'`. |
| **3** | Did they use the same data split? | **YES.** Both were evaluated on the identical single Purged Validation fold (`frxEURUSD` M15 rows `[16936, 20560]`, 3,625 bars). |
| **4** | Did they use the same feature set? | **YES.** Both utilized the complete set of 43 engineered features. |
| **5** | Did they use the same class weighting? | **YES.** Both configured `class_weight="balanced"`. |
| **6** | Did they use the same random seed? | **YES.** Both set `random_state=42`. |
| **7** | Did they use the same preprocessing? | **YES.** Both applied `StandardScaler` fitted strictly on the Train fold (`rows [0, 16931]`). |
| **8** | Was evaluation before or after probability calibration? | **BEFORE calibration.** Both metrics represent raw uncalibrated validation predictions (`model.predict(X_val_s)`). |
| **9** | Was it a validation fold or walk-forward average? | **Validation Fold.** Both are single-fold validation metrics. (In 4-fold walk-forward validation in `GATE_22_WALK_FORWARD.csv`, mean balanced accuracy was `0.4619`). |

---

## 3. Side-by-Side Comparison of Model Parameters

```text
================================================================================
HYPERPARAMETER COMPARISON: TRIAL_08 vs TRIAL_06
================================================================================
Parameter                  TRIAL_08 (Comparison Table)    TRIAL_06 (Report & Candidate B)
--------------------------------------------------------------------------------
Model                      HistGradientBoosting           HistGradientBoosting
class_weight               balanced                       balanced
learning_rate              0.10                           0.03   <-- (Root Cause)
max_iter                   100                            100
min_samples_leaf           20                             20
l2_regularization          0.0                            0.0
random_state               42                             42
Feature Set                All 43 features                All 43 features
Validation Balanced Acc    0.4887                         0.5036
Validation Macro F1        0.3986                         0.3764
Validation Brier (Macro)   0.1146                         0.1463
================================================================================
```

---

## 4. Canonical Metric Declaration & Audit Standard

Under Gate 22R governance:
- **Canonical Baseline HGB (Balanced, lr=0.1):** **`0.4887`** balanced accuracy, **`0.3986`** Macro F1.
- **Canonical Tuned HGB (Candidate B, lr=0.03):** **`0.5036`** balanced accuracy, **`0.3764`** Macro F1.
- **Rule of Integrity:** Neither metric shall be favored over the other without explicitly stating its associated `learning_rate` parameter. All documentation must distinguish between default benchmark models and tuned candidate models.
