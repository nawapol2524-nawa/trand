#!/usr/bin/env python3
"""
Continuous Training CLI Runner & Scheduler
=========================================
Institutional Continuous Retraining Standard for Gate 24
Executes continuous training jobs triggered by CRON, INTERVAL, MANUAL, or NEW_DATA.

Modes:
- Retrain: runs full pre-flight, walk-forward cross-validation, fits candidate model, registers artifact
- --dry-run: validates pipeline and preflight checks without saving artifacts or mutating registry
- --audit: inspects ModelRegistry, champion status, and retraining readiness
- --promote <model_id>: manually gates challenger promotion to CHAMPION
- --rollback: rolls back current champion to previous champion
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from ai_forex_bot.config.settings import settings
from ai_forex_bot.models.registry import ModelRegistry, ModelLifecycleState
from ai_forex_bot.ai.training.continuous_trainer import ContinuousTrainer


def print_banner(title: str) -> None:
    print("=" * 80)
    print(f"GATE 24 CONTINUOUS TRAINING — {title.upper()}")
    print("=" * 80)


def handle_audit(symbol: str, timeframe: str, min_new_samples: int) -> int:
    print_banner("System Audit & Governance Status")
    registry = ModelRegistry()
    champion = registry.get_champion()

    print(f"Registry File: {registry.registry_file}")
    print(f"Total Registered Models: {len(registry.models)}")
    print(f"Current Champion: {champion.model_id if champion else 'NONE'}")
    print(f"Previous Champion: {registry.previous_champion_id or 'NONE'}")
    print(f"Last Registry Update: {registry.last_updated or 'NEVER'}")
    print("-" * 80)

    if registry.models:
        print(f"{'MODEL ID':<42} {'STATE':<12} {'BAL_ACC':<10} {'ROWS':<8}")
        print("-" * 80)
        for m in registry.models.values():
            bal_acc = m.validation_metrics.get("balanced_accuracy", 0.0)
            print(f"{m.model_id:<42} {m.state.value:<12} {bal_acc:<10.4f} {m.train_row_count:<8}")
        print("-" * 80)

    trainer = ContinuousTrainer(symbol=symbol, timeframe=timeframe, min_new_samples=min_new_samples, registry=registry)
    preflight = trainer.run_preflight_checks()
    print(f"Retraining Preflight Status: {'PASS' if preflight.passed else 'REJECT'}")
    print(f"Preflight Reason: {preflight.reason}")
    print(f"Preflight Metrics: {json.dumps(preflight.metrics, indent=2)}")
    print("=" * 80)
    return 0


def handle_promotion(model_id: str, force: bool = False) -> int:
    print_banner(f"Model Promotion Gate: {model_id}")
    registry = ModelRegistry()
    success = registry.promote_challenger_to_champion(
        model_id=model_id,
        force=force,
        reason="CLI_MANUAL_GATED_PROMOTION"
    )
    if success:
        print(f"[SUCCESS] Model '{model_id}' promoted to CHAMPION.")
        print(f"New Champion: {registry.champion_id}")
        print(f"Previous Champion (demoted to ROLLBACK): {registry.previous_champion_id}")
        trainer = ContinuousTrainer(registry=registry)
        trainer.log_event("MANUAL_PROMOTION", {
            "promoted_model_id": model_id,
            "previous_champion": registry.previous_champion_id,
            "forced": force
        })
        return 0
    else:
        print(f"[REJECTED] Model '{model_id}' could not be promoted to CHAMPION.")
        return 1


def handle_rollback() -> int:
    print_banner("Champion Rollback Execution")
    registry = ModelRegistry()
    curr_champ = registry.champion_id
    success = registry.rollback_to_previous_champion(reason="CLI_EXPLICIT_ROLLBACK")
    if success:
        print(f"[SUCCESS] Champion rolled back.")
        print(f"Restored Champion: {registry.champion_id}")
        print(f"Demoted Model: {curr_champ}")
        trainer = ContinuousTrainer(registry=registry)
        trainer.log_event("MANUAL_ROLLBACK", {
            "restored_champion": registry.champion_id,
            "demoted_model": curr_champ
        })
        return 0
    else:
        print(f"[FAILED] Rollback failed. Ensure a valid previous champion exists in registry.")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Gate 24 Scheduled Continuous Retraining & Model Registry Runner"
    )
    parser.add_argument("--symbol", type=str, default="frxEURUSD", help="Trading pair symbol")
    parser.add_argument("--timeframe", type=str, default="M15", help="Bar timeframe")
    parser.add_argument(
        "--trigger",
        type=str,
        default="MANUAL",
        choices=["MANUAL", "CRON", "INTERVAL", "NEW_DATA"],
        help="Trigger source"
    )
    parser.add_argument("--min-new-samples", type=int, default=200, help="Minimum new sample threshold")
    parser.add_argument("--dry-run", action="store_true", help="Perform pre-flight and prep without fitting")
    parser.add_argument("--audit", action="store_true", help="Audit model registry and readiness without retraining")
    parser.add_argument("--force", action="store_true", help="Force execution even if preflight samples check fails")
    parser.add_argument("--promote", type=str, default=None, help="Promote specified model_id to CHAMPION")
    parser.add_argument("--rollback", action="store_true", help="Roll back current champion to previous champion")

    args = parser.parse_args()

    if args.audit:
        sys.exit(handle_audit(args.symbol, args.timeframe, args.min_new_samples))

    if args.promote:
        sys.exit(handle_promotion(args.promote, force=args.force))

    if args.rollback:
        sys.exit(handle_rollback())

    print_banner(f"Continuous Retraining Pipeline ({args.trigger})")
    print(f"Target: {args.symbol} {args.timeframe}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'FULL RETRAINING'}")
    print(f"Enforce Auto-Promotion: STRICTLY FALSE (Zero silent promotion)")
    print(f"Live Trading: STRICTLY FALSE")
    print("-" * 80)

    trainer = ContinuousTrainer(
        symbol=args.symbol,
        timeframe=args.timeframe,
        min_new_samples=args.min_new_samples,
        auto_promotion=False
    )

    result = trainer.execute_retraining(
        trigger=args.trigger,
        dry_run=args.dry_run,
        force_preflight=args.force
    )

    print("\nEXECUTION RESULT:")
    print(json.dumps(result, indent=2))

    if result.get("success"):
        print("\n[PASS] Continuous training process finished successfully.")
        sys.exit(0)
    else:
        print(f"\n[REJECTED/FAILED] {result.get('reason', 'Unknown failure')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
