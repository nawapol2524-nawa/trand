import ccxt
exchange = ccxt.binance({'options': {'defaultType': 'spot'}})
exchange.set_sandbox_mode(True)
markets = exchange.load_markets()
cheap_coins = []
for symbol in markets:
    if symbol.endswith('/USDT'):
        ticker = exchange.fetch_ticker(symbol)
        price = ticker['last']
        if price and price < 0.05:
            cheap_coins.append((symbol, price))

for coin, price in cheap_coins:
    print(f"{coin}: ${price}")
