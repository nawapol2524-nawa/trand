"""
Unit Tests: Double-Barrel Risk & Partial Take-Profit Execution
=============================================================
Validates:
1. Partial close 50% lot reduction, balance credit, and margin recalculation.
2. Dynamic breakeven lock updating remaining position SL atomically (+1 pip buffer).
3. Complete trade lifecycle: partial TP trigger followed by market reversal to breakeven,
   verifying net profit remains positive.
4. Daily profit target cutoff, daily loss cutoff, and UTC midnight reset.
"""

import unittest
from datetime import datetime, timezone

from ai_forex_bot.config.settings import settings
from ai_forex_bot.execution.paper_broker import PaperBroker
from ai_forex_bot.risk.risk_engine import RiskEngine, RiskDecision, AccountState, Position


class TestDoubleBarrelRisk(unittest.TestCase):
    def setUp(self):
        self.broker = PaperBroker(initial_balance=1000.0, leverage=100.0, random_seed=42)
        self.broker.connect()
        # Initial quote for EUR/USD
        self.broker.set_quote("frxEURUSD", bid=1.10000, ask=1.10012, timestamp=1789700000)

    def test_partial_close_lot_reduction_and_balance_credit(self):
        """
        Verify partial close reduces position size by fraction (50%),
        proportionally credits gross & net PnL to balance, and updates margin.
        """
        initial_balance = self.broker.balance
        # Place order for 0.10 lots
        order = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0950,
            tp_price=1.1050,
            idempotency_key="partial_test_1"
        )
        self.assertEqual(order["status"], "FILLED")
        pos_id = order["order_id"]
        entry_price = order["fill_price"]
        comm_usd = order["commission_usd"]
        self.assertAlmostEqual(self.broker.balance, initial_balance - comm_usd, places=2)

        # Margin with 0.10 lots: (0.10 * 100,000 * entry_price) / 100
        initial_used_margin = self.broker.used_margin
        self.assertGreater(initial_used_margin, 0.0)

        # Price moves favorably by +20 pips
        pip_size = 0.0001
        exit_price = entry_price + (20.0 * pip_size)

        # Execute 50% partial close
        balance_before_close = self.broker.balance
        part_res = self.broker.partial_close_position(
            position_id=pos_id,
            fraction=0.5,
            exit_price=exit_price,
            exit_reason="PARTIAL_TP"
        )
        self.assertEqual(part_res["status"], "PARTIALLY_CLOSED")
        self.assertEqual(part_res["remaining_lot_size"], 0.05)

        # Position remaining in broker
        self.assertIn(pos_id, self.broker.positions)
        remaining_pos = self.broker.positions[pos_id]
        self.assertEqual(remaining_pos["lot_size"], 0.05)

        # Used margin should be halved
        self.assertAlmostEqual(self.broker.used_margin, initial_used_margin * 0.5, places=2)

        # 50% lot is 0.05 lots. Gross PnL: 20 pips * 10 $/pip * 0.05 = $10.00
        expected_gross_pnl = 20.0 * 10.0 * 0.05
        self.assertAlmostEqual(part_res["trade"]["gross_pnl"], expected_gross_pnl, places=2)
        self.assertAlmostEqual(self.broker.balance, balance_before_close + expected_gross_pnl, places=2)

        # Check closed trades history
        self.assertEqual(len(self.broker.closed_trades), 1)
        ct = self.broker.closed_trades[0]
        self.assertEqual(ct["exit_reason"], "PARTIAL_TP_50%")
        self.assertEqual(ct["lot_size"], 0.05)
        self.assertTrue(ct.get("is_partial", False))

        # Check broker reconciliation is synchronized
        audit = self.broker.reconcile()
        self.assertTrue(audit["is_synchronized"])
        self.assertAlmostEqual(audit["margin_discrepancy"], 0.0, places=4)
        self.assertAlmostEqual(audit["equity_discrepancy"], 0.0, places=4)

    def test_dynamic_breakeven_lock_updating_remaining_sl(self):
        """
        Verify Double-Barrel processor in on_bar:
        - Detects partial TP (+15 pips).
        - Executes 50% partial close.
        - Moves remaining stop loss to entry_price + 1.0 pip (breakeven lock).
        - Marks partial_tp_hit and breakeven_locked flags.
        Also verifies SELL direction and direct modify_position.
        """
        pip_size = 0.0001
        # 1. BUY Position Test
        order_buy = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=0.10,
            sl_price=1.0980,
            tp_price=1.1050,
            partial_tp_pips=15.0,
            buffer_pips=1.0,
            idempotency_key="db_buy_test"
        )
        self.assertEqual(order_buy["status"], "FILLED")
        buy_pos_id = order_buy["order_id"]
        buy_entry = order_buy["fill_price"]
        expected_ptp_buy = buy_entry + (15.0 * pip_size)
        expected_be_sl_buy = buy_entry + (1.0 * pip_size)

        # Feed bar that touches partial TP (high >= expected_ptp_buy)
        bar_tp = {
            "symbol": "frxEURUSD",
            "epoch": 1789700900,
            "open": buy_entry + 0.0005,
            "high": expected_ptp_buy + 0.0005,
            "low": buy_entry + 0.0002,
            "close": expected_ptp_buy
        }
        closed_on_bar = self.broker.on_bar(bar_tp)
        self.assertEqual(len(closed_on_bar), 1)
        self.assertEqual(closed_on_bar[0]["exit_reason"], "PARTIAL_TP_50%")

        # Inspect remaining open position
        self.assertIn(buy_pos_id, self.broker.positions)
        pos = self.broker.positions[buy_pos_id]
        self.assertEqual(pos["lot_size"], 0.05)
        self.assertTrue(pos["partial_tp_hit"])
        self.assertTrue(pos["breakeven_locked"])
        self.assertAlmostEqual(pos["sl_price"], expected_be_sl_buy, places=5)

        # Close out BUY position to clean up
        self.broker.close_position(buy_pos_id)

        # 2. SELL Position Test
        order_sell = self.broker.place_order(
            symbol="frxEURUSD",
            direction="SELL",
            lot_size=0.10,
            sl_price=1.1030,
            tp_price=1.0950,
            partial_tp_pips=15.0,
            buffer_pips=1.0,
            idempotency_key="db_sell_test"
        )
        self.assertEqual(order_sell["status"], "FILLED")
        sell_pos_id = order_sell["order_id"]
        sell_entry = order_sell["fill_price"]
        expected_ptp_sell = sell_entry - (15.0 * pip_size)
        expected_be_sl_sell = sell_entry - (1.0 * pip_size)

        # Feed bar that touches SELL partial TP (low <= expected_ptp_sell)
        bar_sell_tp = {
            "symbol": "frxEURUSD",
            "epoch": 1789701800,
            "open": sell_entry - 0.0005,
            "high": sell_entry - 0.0002,
            "low": expected_ptp_sell - 0.0005,
            "close": expected_ptp_sell
        }
        closed_sell = self.broker.on_bar(bar_sell_tp)
        self.assertEqual(len(closed_sell), 1)
        self.assertEqual(closed_sell[0]["exit_reason"], "PARTIAL_TP_50%")

        pos_s = self.broker.positions[sell_pos_id]
        self.assertEqual(pos_s["lot_size"], 0.05)
        self.assertTrue(pos_s["partial_tp_hit"])
        self.assertTrue(pos_s["breakeven_locked"])
        self.assertAlmostEqual(pos_s["sl_price"], expected_be_sl_sell, places=5)

        # 3. Test modify_position directly
        mod_ok = self.broker.modify_position(sell_pos_id, sl_price=1.1000, tp_price=1.0900)
        self.assertTrue(mod_ok)
        self.assertEqual(self.broker.positions[sell_pos_id]["sl_price"], 1.1000)
        self.assertEqual(self.broker.positions[sell_pos_id]["tp_price"], 1.0900)

        mod_fail = self.broker.modify_position("invalid_position_id", sl_price=1.1000)
        self.assertFalse(mod_fail)

    def test_complete_trade_lifecycle_partial_tp_then_reversal_to_breakeven(self):
        """
        Verify complete trade lifecycle where market reaches partial TP (+15 pips),
        locks in breakeven (+1 pip buffer), and then reverses, triggering the breakeven SL.
        Validates that overall net profit remains strictly positive!
        """
        initial_balance = self.broker.balance
        pip_size = 0.0001
        lot_size = 0.10

        order = self.broker.place_order(
            symbol="frxEURUSD",
            direction="BUY",
            lot_size=lot_size,
            sl_price=1.0980,
            tp_price=1.1050,
            partial_tp_pips=15.0,
            buffer_pips=1.0,
            idempotency_key="lifecycle_order_1"
        )
        self.assertEqual(order["status"], "FILLED")
        pos_id = order["order_id"]
        entry_price = order["fill_price"]
        comm_usd = order["commission_usd"]
        # Commission deducted at entry ($6/lot * 0.10 = $0.60)
        self.assertAlmostEqual(comm_usd, 0.60, places=2)

        ptp_price = entry_price + (15.0 * pip_size)
        breakeven_sl_price = entry_price + (1.0 * pip_size)

        # Bar 1: Price spikes up to partial TP (high >= ptp_price)
        bar1 = {
            "symbol": "frxEURUSD",
            "epoch": 1789700900,
            "open": entry_price + 0.0002,
            "high": ptp_price + 0.0005,
            "low": entry_price + 0.0001,
            "close": ptp_price
        }
        closed_b1 = self.broker.on_bar(bar1)
        self.assertEqual(len(closed_b1), 1)
        self.assertEqual(closed_b1[0]["exit_reason"], "PARTIAL_TP_50%")
        self.assertEqual(closed_b1[0]["lot_size"], 0.05)
        # 15 pips on 0.05 lot = $7.50
        self.assertAlmostEqual(closed_b1[0]["gross_pnl"], 7.50, places=2)

        # Verify position is still open with 50% lot and updated SL
        self.assertIn(pos_id, self.broker.positions)
        pos = self.broker.positions[pos_id]
        self.assertEqual(pos["lot_size"], 0.05)
        self.assertTrue(pos["breakeven_locked"])
        self.assertAlmostEqual(pos["sl_price"], breakeven_sl_price, places=5)

        # Bar 2: Market violently reverses! Drops below breakeven SL (low <= breakeven_sl_price)
        bar2 = {
            "symbol": "frxEURUSD",
            "epoch": 1789701800,
            "open": ptp_price - 0.0005,
            "high": ptp_price,
            "low": entry_price - 0.0005,  # Well below breakeven SL
            "close": entry_price
        }
        closed_b2 = self.broker.on_bar(bar2)
        self.assertEqual(len(closed_b2), 1)
        self.assertEqual(closed_b2[0]["exit_reason"], "BREAKEVEN_SL")
        self.assertEqual(closed_b2[0]["lot_size"], 0.05)

        # Position should now be completely closed
        self.assertEqual(len(self.broker.positions), 0)
        self.assertEqual(len(self.broker.closed_trades), 2)

        # Calculate total realized financial performance
        trade1 = self.broker.closed_trades[0]
        trade2 = self.broker.closed_trades[1]
        total_gross_pnl = trade1["gross_pnl"] + trade2["gross_pnl"]
        # Trade 1 gross = +$7.50, Trade 2 gross at breakeven SL = +1.0 pip * 10 * 0.05 = +$0.50 (or >= 0)
        self.assertGreaterEqual(trade2["gross_pnl"], 0.0)

        net_profit_after_all_costs = self.broker.balance - initial_balance
        # Net balance change: +$7.50 + $0.50 - $0.60 commission = +$7.40
        self.assertGreater(net_profit_after_all_costs, 0.0)
        self.assertGreaterEqual(total_gross_pnl - comm_usd, 5.0)  # Solid net profit!

        # Reconciliation check
        audit = self.broker.reconcile()
        self.assertTrue(audit["is_synchronized"])
        self.assertEqual(audit["open_position_count"], 0)
        self.assertEqual(audit["closed_trade_count"], 2)

    def test_daily_profit_target_and_loss_cutoff(self):
        """
        Verify RiskEngine:
        1. Signals rejected with DAILY_PROFIT_TARGET_REACHED when daily realized PnL >= target.
        2. Signals rejected with DAILY_LOSS_LIMIT_REACHED when daily realized PnL <= -limit.
        3. UTC midnight boundary resets daily realized PnL and permits trading again.
        """
        # Set daily profit target = $15.00, daily loss limit = $5.00
        risk = RiskEngine(
            daily_profit_target_usd=15.0,
            daily_loss_limit=5.0
        )
        self.assertEqual(risk.daily_profit_target_usd, 15.0)
        self.assertEqual(risk.daily_loss_limit, 5.0)

        dt_trade = datetime(2026, 9, 19, 10, 0, 0, tzinfo=timezone.utc)
        account = AccountState(balance=1000.0, equity=1000.0, free_margin=1000.0)

        # Initially, signal validation should APPROVE
        dec, reason, _ = risk.validate_signal(current_dt=dt_trade)
        self.assertEqual(dec, RiskDecision.APPROVE)
        self.assertEqual(reason, "APPROVED")

        # 1. Test Daily Profit Target Cutoff
        # Trade 1: +$10.00
        risk.record_closed_trade(10.00, dt_trade)
        self.assertEqual(risk.daily_realized_pnl, 10.00)
        dec, reason, _ = risk.validate_signal(current_dt=dt_trade)
        self.assertEqual(dec, RiskDecision.APPROVE)

        # Trade 2: +$6.00 (Total daily realized PnL = +$16.00 >= $15.00)
        risk.record_closed_trade(6.00, dt_trade)
        self.assertEqual(risk.daily_realized_pnl, 16.00)

        # Signal MUST be rejected
        res = risk.validate_signal(current_dt=dt_trade)
        self.assertEqual(res.decision, RiskDecision.REJECT)
        self.assertEqual(res.reason, "DAILY_PROFIT_TARGET_REACHED")
        self.assertIn("Daily profit target reached", res.detail)

        # validate_new_order MUST also be rejected
        dec_order, reason_order, _ = risk.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=1.0,
            account=account,
            open_positions=[],
            current_dt=dt_trade
        )
        self.assertEqual(dec_order, RiskDecision.REJECT)
        self.assertEqual(reason_order, "DAILY_PROFIT_TARGET_REACHED")

        # 2. Test UTC Midnight Reset
        dt_midnight = datetime(2026, 9, 20, 0, 1, 0, tzinfo=timezone.utc)
        dec_next_day, reason_next_day, _ = risk.validate_signal(current_dt=dt_midnight)
        self.assertEqual(dec_next_day, RiskDecision.APPROVE)
        self.assertEqual(reason_next_day, "APPROVED")
        self.assertEqual(risk.daily_realized_pnl, 0.0)
        self.assertEqual(risk.current_date, "2026-09-20")

        # 3. Test Daily Loss Limit Cutoff
        # Trade loss: -$6.00 (below -daily_loss_limit -$5.00)
        risk.record_closed_trade(-6.00, dt_midnight)
        self.assertEqual(risk.daily_realized_pnl, -6.00)

        # Signal MUST be rejected with DAILY_LOSS_LIMIT_REACHED
        res_loss = risk.validate_signal(current_dt=dt_midnight)
        self.assertEqual(res_loss.decision, RiskDecision.REJECT)
        self.assertEqual(res_loss.reason, "DAILY_LOSS_LIMIT_REACHED")

        # validate_new_order MUST also be rejected
        dec_order_loss, reason_order_loss, _ = risk.validate_new_order(
            symbol="frxEURUSD",
            direction="BUY",
            current_spread_pips=1.0,
            account=account,
            open_positions=[],
            current_dt=dt_midnight
        )
        self.assertEqual(dec_order_loss, RiskDecision.REJECT)
        self.assertEqual(reason_order_loss, "DAILY_LOSS_LIMIT_REACHED")


if __name__ == "__main__":
    unittest.main()
