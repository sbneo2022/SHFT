from abc import ABC, abstractmethod
from typing import Type, Optional

from lib.constants import KEY
from lib.factory import AbstractFactory
from lib.supervisor import AbstractSupervisor
from lib.timer import AbstractTimer


class AbstractStream(ABC):
    def __init__(self, config: dict, supervisor: AbstractSupervisor, factory: AbstractFactory, timer: AbstractTimer):
        self._config = config
        self._supervisor = supervisor
        self._factory = factory
        self._timer = timer

    @abstractmethod
    def Run(self, start_timestamp: int = 0, end_timestamp: int = 0):
        pass

def get_stream(config: dict, exchange: Optional[str] = None) -> Type[AbstractStream]:
    from lib.stream.okex_perp_websocket_stream import OkexPerpWebsocketStream
    from lib.stream.okex_spot_websocket_stream import OkexSpotWebsocketStream
    from lib.stream.huobi_swap_websocket_stream import HuobiSwapWebsocketStream
    from lib.stream.binance_futures_websocket_stream import BinanceFuturesWebsocketStream
    from lib.stream.binance_spot_websocket_stream import BinanceSpotWebsocketStream
    from lib.stream.binance_dex_websocket_stream import BinanceDexWebsocketStream
    from lib.stream.ftx_perp_websocket_stream import FtxPerpWebsocketStream
    from lib.stream.perpetual_protocol_websocket_stream import PerpetualProtocolWebsocketStream
    from lib.stream.virtual_stream import VirtualStream

    if config.get(KEY.MODE, None) == KEY.SIMULATION:
        return VirtualStream

    else:
        exchange = exchange or config[KEY.EXCHANGE]

        return {
            KEY.EXCHANGE_BINANCE_FUTURES: BinanceFuturesWebsocketStream,
            KEY.EXCHANGE_BINANCE_SPOT: BinanceSpotWebsocketStream,
            KEY.EXCHANGE_BINANCE_DEX: BinanceDexWebsocketStream,
            KEY.EXCHANGE_OKEX_PERP: OkexPerpWebsocketStream,
            KEY.EXCHANGE_OKEX_SPOT: OkexSpotWebsocketStream,
            KEY.EXCHANGE_HUOBI_SWAP: HuobiSwapWebsocketStream,
            KEY.EXCHANGE_FTX_PERP: FtxPerpWebsocketStream,
            KEY.EXCHANGE_PERPETUAL_PROTOCOL: PerpetualProtocolWebsocketStream,
        }[exchange]