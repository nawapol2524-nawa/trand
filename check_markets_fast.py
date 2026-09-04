import ccxt
exchange = ccxt.binance({'options': {'defaultType': 'spot'}})
exchange.set_sandbox_mode(True)
exchange.load_markets()
tickers = exchange.fetch_tickers()
cheap_coins = []
for symbol, ticker in tickers.items():
    if symbol.endswith('/USDT'):
        price = ticker['last']
        if price and price < 0.05:
            cheap_coins.append((symbol, price))

# เรียงจากแพงไปถูก
cheap_coins.sort(key=lambda x: x[1], reverse=True)
for coin, price in cheap_coins:
    print(f"{coin}: ${price}")
