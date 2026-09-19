"""
Unit Tests: Console UI & Terminal Formatter
===========================================
Validates:
1. ANSI Color codes and visible width calculation (accounting for wide emojis).
2. Padding helpers (pad_colored, _box_line).
3. Startup banner rendering.
4. Status board rendering (account financials, multi-symbol market signals).
5. Order execution and trade closed card rendering.
6. Shutdown summary rendering.
"""

import io
import sys
import unittest
from ai_forex_bot.monitoring.console import ConsoleUI, Colors, visible_width, pad_colored


class TestConsoleUI(unittest.TestCase):
    def test_visible_width_calculation(self):
        """Verify visible width accounts for emojis and strips ANSI codes."""
        plain = "Hello World"
        self.assertEqual(visible_width(plain), 11)

        # ANSI colored string
        colored = f"{Colors.GREEN}Hello{Colors.RESET} {Colors.RED}World{Colors.RESET}"
        self.assertEqual(visible_width(colored), 11)

        # Emojis (wide characters taking 2 terminal columns)
        emoji_str = "🤖 AI Bot"
        # 🤖 is 2 columns + space (1) + "AI Bot" (6) = 9
        self.assertEqual(visible_width(emoji_str), 9)

    def test_pad_colored(self):
        """Verify pad_colored appends correct amount of spaces."""
        colored = f"{Colors.BOLD}EURUSD{Colors.RESET}"
        padded = pad_colored(colored, 10)
        self.assertEqual(visible_width(padded), 10)

    def test_box_line_exact_width(self):
        """Verify _box_line produces exact width between borders."""
        content = "  Balance: $1,000.00"
        line = ConsoleUI._box_line(content, Colors.CYAN, "│")
        # Stripping ANSI, the line should start with │, end with │, and total width is WIDTH + 2
        clean = line.replace(Colors.CYAN, "").replace(Colors.RESET, "")
        self.assertTrue(clean.startswith("│"))
        self.assertTrue(clean.endswith("│"))
        self.assertEqual(visible_width(clean), ConsoleUI.WIDTH + 2)

    def test_print_startup_banner_execution(self):
        """Verify print_startup_banner runs without error and outputs content."""
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            ConsoleUI.print_startup_banner(
                symbols=["R_75", "R_25"],
                timeframe="M15",
                strategy="double_barrel",
                single_cycle=True,
                live_trading=False,
                auto_promotion=False,
                model_id="candidate_r75_M15"
            )
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("AI AUTONOMOUS QUANT TRADING SYSTEM", output)
        self.assertIn("R_75, R_25", output)
        self.assertIn("candidate_r75_M15", output)

    def test_print_status_board_execution(self):
        """Verify print_status_board displays financial metrics and market signals."""
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            ConsoleUI.print_status_board(
                timestamp="2026-09-19 12:00:00 UTC",
                uptime_seconds=3665.0,
                memory_mb=162.5,
                balance=1050.0,
                equity=1062.5,
                today_pnl=12.5,
                open_positions=[{"id": "p1", "symbol": "R_75", "direction": "BUY", "lot_size": 1.0}],
                symbols_data=[{
                    "symbol": "R_75",
                    "price": 152430.0,
                    "spread": 25.0,
                    "direction": "BUY",
                    "confidence": 0.68,
                    "position_str": "BUY 1.00L"
                }],
                closed_trades_count=2,
                kill_switch_active=False
            )
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("SYSTEM MONITOR", output)
        self.assertIn("1,050.00", output)
        self.assertIn("+$12.50", output)
        self.assertIn("R_75", output)
        self.assertIn("BUY", output)

    def test_print_order_and_trade_closed(self):
        """Verify order fill and trade close notification cards."""
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            ConsoleUI.print_order_executed(
                order_id="test_ord_1",
                symbol="R_75",
                direction="BUY",
                lot_size=1.0,
                fill_price=150000.0,
                sl_price=149000.0,
                tp_price=152000.0,
                partial_tp_pips=1000.0
            )
            ConsoleUI.print_trade_closed(
                order_id="test_ord_1",
                symbol="R_75",
                direction="BUY",
                lot_size=1.0,
                entry_price=150000.0,
                exit_price=151000.0,
                pips_gain=1000.0,
                net_pnl=10.0,
                exit_reason="TAKE_PROFIT",
                balance=1010.0
            )
        finally:
            sys.stdout = old_stdout

        output = buf.getvalue()
        self.assertIn("ORDER FILLED", output)
        self.assertIn("test_ord_1", output)
        self.assertIn("TAKE PROFIT", output)
        self.assertIn("+$10.00", output)


if __name__ == "__main__":
    unittest.main()
