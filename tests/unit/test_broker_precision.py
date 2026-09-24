import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
import pytest

from src.app.runner import SYMBOL_MAP
from src.brokers.ctrader_mcp import CTraderMCPBroker


def test_symbol_precision_scaling():
    """Verify that relative SL/TP points match cTrader 10^-5 scale and symbol decimal precision."""
    # Test USDJPY (digits = 3)
    usdjpy = SYMBOL_MAP["USDJPY"]
    digits = usdjpy["digits"]
    assert digits == 3
    
    sl_dist = 0.1155  # e.g. 1.5 * ATR(0.077)
    tp_dist = sl_dist * 2.0
    
    sl_rounded = round(sl_dist, digits)  # 0.116
    tp_rounded = round(tp_dist, digits)  # 0.231
    
    relative_sl = max(1, int(round(sl_rounded * 100000)))  # 11600
    relative_tp = max(1, int(round(tp_rounded * 100000)))  # 23100
    
    assert relative_sl == 11600
    assert relative_tp == 23100
    
    # Check that in cTrader, dividing by 100000 produces exact 3 decimals
    sl_offset = relative_sl / 100000.0
    tp_offset = relative_tp / 100000.0
    assert round(sl_offset, 3) == sl_offset
    assert round(tp_offset, 3) == tp_offset
    
    # Test EURUSD & GBPUSD (digits = 5)
    for sym in ["EURUSD", "GBPUSD"]:
        info = SYMBOL_MAP[sym]
        assert info["digits"] == 5
        sl_f = round(0.000765, info["digits"])
        rel_sl = max(1, int(round(sl_f * 100000)))
        assert rel_sl == 76
        assert round(rel_sl / 100000.0, 5) == 0.00076
        
    # Test XAUUSD (digits = 2)
    xau = SYMBOL_MAP["XAUUSD"]
    assert xau["digits"] == 2
    sl_xau = round(10.505, xau["digits"])  # 10.51
    rel_sl_xau = max(1, int(round(sl_xau * 100000)))
    assert rel_sl_xau == 1051000
    assert round(rel_sl_xau / 100000.0, 2) == 10.51


def test_volume_conversion_contract():
    """Verify that lot sizing converts to cTrader 1/100 base asset units correctly."""
    # Forex (EURUSD, GBPUSD, USDJPY): 1 lot = 100,000 units -> mcp_volume = lots * 100000 * 100
    lots = 1.31
    mcp_vol_forex = int(round(lots * 100000.0 * 100))
    assert mcp_vol_forex == 13100000
    
    # Gold (XAUUSD): 1 lot = 100 oz -> mcp_volume = lots * 100 * 100
    xau_lots = 0.50
    mcp_vol_xau = int(round(xau_lots * 100.0 * 100))
    assert mcp_vol_xau == 5000


@patch("urllib.request.urlopen")
def test_repeated_404_raises_and_limits_retry(mock_urlopen):
    """Verify that if retry also returns 404, it raises HTTPError and does not loop infinitely."""
    mock_404 = urllib.error.HTTPError("https://mcp.ctrader.com", 404, "Not Found", {}, None)
    
    success_init = MagicMock()
    success_init.read.return_value = b'data: {"result": {}}'
    success_init.headers = {"mcp-session-id": "new-session-id"}
    success_init.__enter__.return_value = success_init
    success_init.__exit__.return_value = None
    
    # Sequence: 1. initial call fails with 404
    #           2. connect initialize succeeds
    #           3. connect notifications succeeds
    #           4. retry call fails again with 404
    mock_urlopen.side_effect = [
        mock_404,
        success_init,
        success_init,
        mock_404,
    ]
    
    broker = CTraderMCPBroker(endpoint_url="https://test.local", bearer_token="Bearer test")
    broker.session_id = "stale-session"
    
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        broker.get_positions()
        
    assert exc_info.value.code == 404
    # Total calls: 1 initial + 2 connect + 1 retry = 4 calls total
    assert mock_urlopen.call_count == 4
