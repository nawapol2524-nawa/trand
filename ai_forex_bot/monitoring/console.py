"""
Institutional Console UI & Terminal Dashboard Formatter
========================================================
Provides high-visibility, elegant, and readable console formatting for:
- 24/7 Cloud VPS & Pterodactyl Web Terminals (bot-hosting.net)
- Real-time market ticker & AI signal indicators
- High-contrast trade execution & exit notification cards
- Periodic system health, equity, and PnL status boards
- Graceful shutdown session summaries
"""

import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

ANSI_REGEX = re.compile(r"\x1b\[[0-9;]*m")


class Colors:
    """ANSI color codes with terminal auto-detection."""
    ENABLED = os.getenv("NO_COLOR") is None and os.getenv("TERM") != "dumb"

    RESET = "\033[0m" if ENABLED else ""
    BOLD = "\033[1m" if ENABLED else ""
    DIM = "\033[2m" if ENABLED else ""

    RED = "\033[91m" if ENABLED else ""
    GREEN = "\033[92m" if ENABLED else ""
    YELLOW = "\033[93m" if ENABLED else ""
    BLUE = "\033[94m" if ENABLED else ""
    MAGENTA = "\033[95m" if ENABLED else ""
    CYAN = "\033[96m" if ENABLED else ""
    WHITE = "\033[97m" if ENABLED else ""

    BG_GREEN = "\033[42m\033[30m" if ENABLED else ""
    BG_RED = "\033[41m\033[37m" if ENABLED else ""
    BG_BLUE = "\033[44m\033[37m" if ENABLED else ""


def visible_width(s: str) -> int:
    """Calculates visible column width on terminal taking ANSI codes and wide emojis into account."""
    clean = ANSI_REGEX.sub("", s)
    width = 0
    for ch in clean:
        code = ord(ch)
        # Box drawing characters (0x2500 - 0x257F) occupy 1 column
        if 0x2500 <= code <= 0x257F:
            width += 1
        # Wide emojis and symbols occupy 2 columns
        elif code >= 0x2600:
            width += 2
        else:
            width += 1
    return width


def pad_colored(s: str, target_width: int) -> str:
    """Pads a string with ANSI colors to exact target visual width."""
    vw = visible_width(s)
    return s + (" " * max(0, target_width - vw))


class ConsoleUI:
    """High-visibility, stream-friendly console UI renderer."""

    WIDTH = 80

    @classmethod
    def _box_line(cls, content: str, border_color: str, border_char: str = "│") -> str:
        vw = visible_width(content)
        padding = max(0, cls.WIDTH - vw)
        return f"{border_color}{border_char}{Colors.RESET}{content}{' ' * padding}{border_color}{border_char}{Colors.RESET}"

    @classmethod
    def print_startup_banner(
        cls,
        symbols: List[str],
        timeframe: str,
        strategy: str,
        single_cycle: bool = False,
        live_trading: bool = False,
        auto_promotion: bool = False,
        model_id: str = "N/A",
        heartbeat_interval: float = 60.0
    ) -> None:
        """Prints a clean, institutional header banner."""
        c = Colors
        mode_str = f"{c.RED}🔴 LIVE TRADING{c.RESET}" if live_trading else f"{c.GREEN}🟢 PAPER SIMULATION (100% SAFE){c.RESET}"
        sup_mode = f"{c.YELLOW}SINGLE-CYCLE TEST{c.RESET}" if single_cycle else f"{c.CYAN}24/7/365 CONTINUOUS SUPERVISOR{c.RESET}"
        sym_str = ", ".join(symbols)

        line = "─" * cls.WIDTH
        print(f"\n{c.CYAN}╭{line}╮{c.RESET}")
        header_text = f"  {c.BOLD}🤖 AI AUTONOMOUS QUANT TRADING SYSTEM — PRODUCTION ENGINE{c.RESET}"
        print(cls._box_line(header_text, c.CYAN, "│"))
        print(f"{c.CYAN}╰{line}╯{c.RESET}")

        print(f"  {c.BOLD}• Supervisor Mode :{c.RESET} {sup_mode}")
        print(f"  {c.BOLD}• Trading Mode    :{c.RESET} {mode_str}")
        print(f"  {c.BOLD}• Active Symbols  :{c.RESET} {c.BOLD}{sym_str}{c.RESET} ({c.CYAN}{timeframe}{c.RESET})")
        print(f"  {c.BOLD}• Strategy        :{c.RESET} {strategy.title()} (Partial TP 1R + Breakeven Runner)")
        print(f"  {c.BOLD}• Active Model    :{c.RESET} {model_id}")
        print(f"  {c.BOLD}• Safety Gates    :{c.RESET} LIVE_TRADING={str(live_trading).lower()} | AUTO_PROMOTION={str(auto_promotion).lower()}")
        print(f"  {c.BOLD}• Heartbeat Pulse :{c.RESET} Every {heartbeat_interval:.0f}s -> {c.DIM}logs/heartbeat.json{c.RESET}")
        print(f"{c.DIM}{'─' * (cls.WIDTH + 2)}{c.RESET}\n")
        sys.stdout.flush()

    @classmethod
    def print_status_board(
        cls,
        timestamp: str,
        uptime_seconds: float,
        memory_mb: float,
        balance: float,
        equity: float,
        today_pnl: float,
        open_positions: List[Dict[str, Any]],
        symbols_data: List[Dict[str, Any]],
        closed_trades_count: int,
        kill_switch_active: bool = False
    ) -> None:
        """Prints a readable, compact periodic status dashboard."""
        c = Colors
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        uptime_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

        pnl_color = c.GREEN if today_pnl > 0 else (c.RED if today_pnl < 0 else c.WHITE)
        pnl_sign = "+" if today_pnl > 0 else ""
        pnl_pct = (today_pnl / balance * 100.0) if balance > 0 else 0.0
        ks_status = f"{c.RED}🔴 HALTED{c.RESET}" if kill_switch_active else f"{c.GREEN}🟢 NORMAL{c.RESET}"

        line = "─" * cls.WIDTH
        print(f"\n{c.CYAN}┌{line}┐{c.RESET}")
        top_bar = f"  {c.BOLD}💓 SYSTEM MONITOR{c.RESET} | {c.DIM}{timestamp}{c.RESET} | Up: {uptime_str} | RAM: {memory_mb:.1f}MB"
        print(cls._box_line(top_bar, c.CYAN, "│"))
        print(f"{c.CYAN}├{line}┤{c.RESET}")

        # Account financials
        fin_line = f"  Balance: ${balance:,.2f}  |  Equity: ${equity:,.2f}  |  PnL: {pnl_color}{pnl_sign}${today_pnl:,.2f} ({pnl_sign}{pnl_pct:.2f}%){c.RESET}"
        print(cls._box_line(fin_line, c.CYAN, "│"))

        stats_line = f"  Open Positions: {len(open_positions)}  |  Closed Trades: {closed_trades_count}  |  Risk Guard: {ks_status}"
        print(cls._box_line(stats_line, c.CYAN, "│"))

        # Market & Signals table
        if symbols_data:
            print(f"{c.CYAN}├{line}┤{c.RESET}")
            col_sym = pad_colored("  SYMBOL", 10)
            col_price = pad_colored("PRICE", 16)
            col_spread = pad_colored("SPREAD", 10)
            col_sig = pad_colored("AI SIGNAL", 20)
            col_pos = pad_colored("POSITION", 18)
            hdr = f"{col_sym}{col_price}{col_spread}{col_sig}{col_pos}"
            print(cls._box_line(f"{c.BOLD}{hdr}{c.RESET}", c.CYAN, "│"))
            for s in symbols_data:
                sym = s.get("symbol", "N/A")
                price = s.get("price", 0.0)
                spread = s.get("spread", 0.0)
                sig = s.get("direction", "HOLD")
                conf = s.get("confidence", 0.0)
                pos = s.get("position_str", "None")

                if sig == "BUY":
                    sig_fmt = f"{c.GREEN}▲ BUY  ({conf*100:.0f}%){c.RESET}"
                elif sig == "SELL":
                    sig_fmt = f"{c.RED}▼ SELL ({conf*100:.0f}%){c.RESET}"
                else:
                    sig_fmt = f"{c.DIM}─ HOLD ({conf*100:.0f}%){c.RESET}"

                price_fmt = f"{price:,.2f}" if price >= 100 else f"{price:.5f}"
                c_sym = pad_colored(f"  {c.BOLD}{sym}{c.RESET}", 10)
                c_price = pad_colored(price_fmt, 16)
                c_spread = pad_colored(f"{spread:.1f}p", 10)
                c_sig = pad_colored(sig_fmt, 20)
                c_pos = pad_colored(pos, 18)
                row_colored = f"{c_sym}{c_price}{c_spread}{c_sig}{c_pos}"
                print(cls._box_line(row_colored, c.CYAN, "│"))

        print(f"{c.CYAN}└{line}┘{c.RESET}\n")
        sys.stdout.flush()

    @classmethod
    def print_order_executed(
        cls,
        order_id: str,
        symbol: str,
        direction: str,
        lot_size: float,
        fill_price: float,
        sl_price: float,
        tp_price: float,
        partial_tp_pips: Optional[float] = None,
        strategy: str = "Double-Barrel"
    ) -> None:
        """Prints a high-contrast card when a trade is entered."""
        c = Colors
        dir_badge = f"{c.BG_GREEN} BUY {c.RESET}" if direction == "BUY" else f"{c.BG_RED} SELL {c.RESET}"

        line = "─" * cls.WIDTH
        print(f"\n{c.GREEN}╔{line}╗{c.RESET}")
        title = f" {c.BOLD}⚡ [ORDER FILLED] #{order_id}{c.RESET}"
        print(cls._box_line(title, c.GREEN, "║"))
        print(f"{c.GREEN}╟{line}╢{c.RESET}")
        print(cls._box_line(f"  Symbol    : {c.BOLD}{symbol}{c.RESET} | Direction: {dir_badge} | Lot: {c.BOLD}{lot_size:.3f}{c.RESET}", c.GREEN, "║"))
        print(cls._box_line(f"  Fill Price: {c.BOLD}{fill_price:,.2f}{c.RESET}", c.GREEN, "║"))
        print(cls._box_line(f"  Stop Loss : {c.RED}{sl_price:,.2f}{c.RESET}", c.GREEN, "║"))
        print(cls._box_line(f"  Target TP : {c.GREEN}{tp_price:,.2f}{c.RESET}", c.GREEN, "║"))
        if partial_tp_pips:
            print(cls._box_line(f"  Strategy  : {strategy} (TP1: +{partial_tp_pips:.1f}p -> Breakeven lock)", c.GREEN, "║"))
        print(f"{c.GREEN}╚{line}╝{c.RESET}\n")
        sys.stdout.flush()

    @classmethod
    def print_trade_closed(
        cls,
        order_id: str,
        symbol: str,
        direction: str,
        lot_size: float,
        entry_price: float,
        exit_price: float,
        pips_gain: float,
        net_pnl: float,
        exit_reason: str,
        balance: float
    ) -> None:
        """Prints a high-contrast notification card when a trade closes."""
        c = Colors
        is_win = net_pnl >= 0
        card_color = c.GREEN if is_win else c.RED
        title_badge = f"{c.BG_GREEN} 🎯 TAKE PROFIT {c.RESET}" if is_win else f"{c.BG_RED} 🛑 STOP LOSS {c.RESET}"
        pnl_sign = "+" if is_win else ""
        pnl_str = f"{card_color}{c.BOLD}{pnl_sign}${net_pnl:,.2f} ({pnl_sign}{pips_gain:,.1f} pips){c.RESET}"

        line = "─" * cls.WIDTH
        print(f"\n{card_color}╔{line}╗{c.RESET}")
        title = f" {title_badge} {c.BOLD}#{order_id} ({symbol}){c.RESET}"
        print(cls._box_line(title, card_color, "║"))
        print(f"{card_color}╟{line}╢{c.RESET}")
        print(cls._box_line(f"  Direction   : {direction} | Lot: {lot_size:.3f} | Reason: {exit_reason}", card_color, "║"))
        print(cls._box_line(f"  Entry ➔ Exit: {entry_price:,.2f} ➔ {exit_price:,.2f}", card_color, "║"))
        print(cls._box_line(f"  Realized PnL: {pnl_str}", card_color, "║"))
        print(cls._box_line(f"  New Balance : {c.BOLD}${balance:,.2f}{c.RESET}", card_color, "║"))
        print(f"{card_color}╚{line}╝{c.RESET}\n")
        sys.stdout.flush()

    @classmethod
    def print_risk_event(cls, symbol: str, event_type: str, detail: str) -> None:
        """Prints risk management alerts (e.g. Breakeven locked, partial TP)."""
        c = Colors
        time_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"{c.YELLOW}[{time_str}] 🛡️  [{symbol}] {event_type}: {detail}{c.RESET}")
        sys.stdout.flush()

    @classmethod
    def print_shutdown_summary(
        cls,
        symbol: str,
        uptime_seconds: float,
        trades_count: int,
        final_balance: float,
        today_pnl: float,
        reason: str = "NORMAL"
    ) -> None:
        """Prints an executive shutdown summary."""
        c = Colors
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        seconds = int(uptime_seconds % 60)
        uptime_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

        pnl_sign = "+" if today_pnl >= 0 else ""
        pnl_color = c.GREEN if today_pnl >= 0 else c.RED

        line = "─" * cls.WIDTH
        print(f"\n{c.CYAN}╭{line}╮{c.RESET}")
        title = f"  {c.BOLD}🛑 SHUTDOWN SUMMARY — AI AUTONOMOUS TRADING BOT{c.RESET}"
        print(cls._box_line(title, c.CYAN, "│"))
        print(f"{c.CYAN}╰{line}╯{c.RESET}")
        print(f"  • Target Symbol(s) : {symbol}")
        print(f"  • Total Uptime     : {uptime_str}")
        print(f"  • Closed Trades    : {trades_count}")
        print(f"  • Session Net PnL  : {pnl_color}{pnl_sign}${today_pnl:,.2f}{c.RESET}")
        print(f"  • Final Balance    : ${final_balance:,.2f}")
        print(f"  • Shutdown Trigger : {reason}")
        print(f"  • State File       : {c.GREEN}artifacts/state/portfolio_state.json{c.RESET}")
        print(f"{c.DIM}{'─' * (cls.WIDTH + 2)}{c.RESET}\n")
        sys.stdout.flush()
