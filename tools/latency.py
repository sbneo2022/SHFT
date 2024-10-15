import os; import sys; sys.path.append(os.path.abspath('..'))

import json
import sys
import time

import websocket

from lib.constants import KEY
from lib.ping import get_binance_lag

WSS_URL = 'wss://fstream.binance.com'
WS_BOOK = '@bookTicker'
WS_TRADES = '@aggTrade'
WS_LEVEL = '@depth10@100ms'



class Latency:
    def __init__(self, symbol):
        self._symbol = symbol

        self._adjust = get_binance_lag()
        self._streams = dict()


    def _handle_trades(self, message):
        pass

    def _handle_book(self, message):
        timestamp = time.time_ns() - self._adjust

        exchange_timestamp = message["T"] * KEY.ONE_MS
        latency = timestamp - exchange_timestamp
        sys.stdout.write(f' {(latency / KEY.ONE_SECOND):0.3f} ')
        sys.stdout.flush()


    def onMessage(self, message):
        try:
            message = json.loads(message)
            fn = self._streams.get(message['stream'], lambda x: None)
            fn(message['data'])
        except Exception as e:
            print('On Message', e)

    def getConnectionString(self):
        self._streams[self._symbol.lower() + WS_TRADES] = self._handle_trades
        self._streams[self._symbol.lower() + WS_BOOK] = self._handle_book
        return WSS_URL + '/stream?streams=' + '/'.join(self._streams.keys())

def getSymbol():
    if len(sys.argv) > 1:
        symbol = sys.argv[1].upper()
        symbol = symbol if 'USDT' in symbol else symbol + 'USDT'
        return symbol
    else:
        sys.stdout.write(f'Usage: {__file__} SYMBOL\n')
        sys.stdout.flush()

if __name__ == '__main__':
    symbol = getSymbol()

    latency = Latency(symbol)

    connection_string = latency.getConnectionString()

    ws = websocket.WebSocketApp(connection_string, on_message=latency.onMessage)

    ws.run_forever()  # Start Websocket connection