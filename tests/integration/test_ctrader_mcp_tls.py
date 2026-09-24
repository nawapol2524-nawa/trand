import urllib.request
import urllib.error
import pytest
from unittest.mock import patch, MagicMock
from src.brokers.ctrader_mcp import CTraderMCPBroker

def test_tls_verification_is_enabled():
    """Verify that TLS verification is NOT bypassed in the codebase."""
    with open("src/brokers/ctrader_mcp.py", "r") as f:
        content = f.read()
    
    assert "CERT_NONE" not in content, "TLS CERT_NONE bypass found in code!"
    assert "check_hostname = False" not in content, "TLS check_hostname bypass found in code!"

@patch("urllib.request.urlopen")
def test_urlopen_propagates_certificate_errors(mock_urlopen):
    """Verify that CERTIFICATE_VERIFY_FAILED is raised and not silenced."""
    mock_urlopen.side_effect = urllib.error.URLError("CERTIFICATE_VERIFY_FAILED")
    
    broker = CTraderMCPBroker(endpoint_url="https://invalid.local", bearer_token="Bearer test")
    
    with pytest.raises(urllib.error.URLError) as exc:
        broker.connect()
        
    assert "CERTIFICATE_VERIFY_FAILED" in str(exc.value)

@patch("urllib.request.urlopen")
def test_404_reconnects_and_retries_once(mock_urlopen):
    """Verify that 404 triggers a single reconnect and retry."""
    # First call to call_tool -> returns 404
    # Re-connect -> returns 200 (for initialized)
    # Re-call call_tool -> returns 200 (success)
    
    # We will simulate the sequence of urlopen calls:
    # 1. tools/call -> 404
    # 2. connect (initialize) -> 200
    # 3. connect (notifications/initialized) -> 200
    # 4. tools/call -> 200
    
    mock_404 = urllib.error.HTTPError(
        "https://mcp.ctrader.com", 404, "Not Found", {}, None
    )
    
    success_resp = MagicMock()
    success_resp.read.return_value = b'data: {"result": {"content": [{"text": "{\\"positions\\": []}"}]}}'
    success_resp.headers = {"mcp-session-id": "new-session"}
    success_resp.__enter__.return_value = success_resp
    success_resp.__exit__.return_value = None

    mock_urlopen.side_effect = [
        mock_404,        # 1. First tool call fails
        success_resp,    # 2. connect() -> initialize
        success_resp,    # 3. connect() -> initialized notification
        success_resp     # 4. Second tool call succeeds
    ]
    
    broker = CTraderMCPBroker(endpoint_url="https://test.local", bearer_token="Bearer test")
    broker.session_id = "old-session"
    
    res = broker.get_positions()
    
    assert res == []
    assert mock_urlopen.call_count == 4
    assert broker.session_id == "new-session"
