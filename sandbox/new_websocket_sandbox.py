import json

import websocket

def onMessage(ws, message):
    message = json.loads(message)
    print(message)

if __name__ == '__main__':
    wss = 'wss://fstream.binance.com/stream?streams=runeusdt@kline_1m'

    ws = websocket.WebSocketApp(wss, on_message=onMessage)

    ws.run_forever()
