import ccxt
exchange = ccxt.binance({'options': {'defaultType': 'spot'}})
exchange.set_sandbox_mode(True)
exchange.load_markets()
for symbol in exchange.markets:
    if 'XAU' in symbol or 'PAXG' in symbol or 'GOLD' in symbol:
        print(f"Found: {symbol}")
