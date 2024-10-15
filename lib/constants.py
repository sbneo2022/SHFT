from decimal import Decimal


class SIDE:
    BUY = "BUY"
    SELL = "SELL"


class ORDER_TYPE:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    LIQUIDATION = "LIQUIDATION"


class ORDER_TAG:
    LIMIT = "L"
    MARKET = "M"
    CONDITIONAL = "C"
    HEDGE = "H"
    TAKE_PROFIT = "MP"
    STOP_LOSSES = "ML"
    STOP_LOSSES_1 = "ML1"
    STOP_LOSSES_2 = "ML2"
    STOP_LOSSES_3 = "ML3"

    @classmethod
    def index(cls, tag):
        map = {
            cls.LIMIT: 1,
            cls.MARKET: 2,
            cls.CONDITIONAL: 3,
            cls.HEDGE: 4,
            cls.TAKE_PROFIT: 5,
            cls.STOP_LOSSES: 6,
            cls.STOP_LOSSES_1: 7,
            cls.STOP_LOSSES_2: 8,
            cls.STOP_LOSSES_3: 9,
        }

        return map.get(tag, 0)


class TIF:
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"


class STATUS:
    NEW = "NEW"
    OPEN = "OPEN"
    CANCELED = "CANCELED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"


class QUEUE:
    QUEUE = "queue"
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    ACCOUNT = "account"
    CANDLES = "candles"
    LEVEL = "level"
    MESSAGE = "message"
    STATUS = "status"


class DB:
    WRITE_DURATION = "_write_duration"
    FREQUENCY = "_frequency"
    MESSAGE = "_message"
    STATE = "_state"
    LEVEL_LATENCY = "_level_latency"
    TRADE_LATENCY = "_trade_latency"
    BOOK_LATENCY = "_book_latency"
    REPLACE_LATENCY = "_replace_latency"

    EVENT = "_event"
    REQUEST = "_request"
    REQUEST_ORDER = "_request_order"
    REQUEST_ORDER10S = "_request_order10s"
    REQUEST_USED = "_request_used"

    MIN_DELTA = "_min_replace_delta"
    MAX_DELTA = "_max_replace_delta"
    CANCEL_ALIGN = "_cancel_align"


# TODO: Replace to Enum (whole codebase). Ex: class KEY(Enum): ...
class KEY:
    PROJECT = "project"

    ID = "id"
    ALIVE = "alive"
    PRODUCT = "product"

    ########## Exchange names
    EXCHANGE_BINANCE_FUTURES = "BINANCE.FUTURES"
    EXCHANGE_BINANCE_SPOT = "BINANCE.SPOT"
    EXCHANGE_BINANCE_DEX = "BINANCE.DEX"
    EXCHANGE_OKEX_PERP = "OKEX.PERP"
    EXCHANGE_OKEX_SPOT = "OKEX.SPOT"
    EXCHANGE_HUOBI_SWAP = "HUOBI.SWAP"
    EXCHANGE_FTX_PERP = "FTX.PERP"
    EXCHANGE_PERPETUAL_PROTOCOL = "PERPETUAL.PROTOCOL"
    EXCHANGE_BITMEX = "BITMEX"
    EXCHANGE_VIRTUAL = "VIRTUAL"
    EXCHANGE_THORCHAIN = "THORCHAIN"

    ########## Exchange parameters
    NODE_URL = "node_url"
    REST_URL = "rest_url"
    WSS_URL = "wss_url"
    API_LIMIT = "api_limit"
    KEY = "key"
    SECRET = "secret"
    LEVERAGE = "leverage"
    GAS_PRICE_GWEI = "gas_price_gwei"
    GAS_MAX = "gas_max"

    ########## Global Latency key
    LATENCY = DB.BOOK_LATENCY

    ########## Tick data keys
    ASK_PRICE: str = "askPrice"
    BID_PRICE: str = "bidPrice"
    ASK_QTY = "askQty"
    BID_QTY = "bidQty"
    ASKS = "asks"
    BIDS = "bids"

    TRADE_PRICE = "trade_price"

    ########## Candle keys
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"
    FINISHED = "finished"

    ########## Level5 and Level10 keys
    ASK_5_QTY = "ask5qty"
    BID_5_QTY = "bid5qty"
    ASK_10_QTY = "ask10qty"
    BID_10_QTY = "bid10qty"

    ########## Funding Rate and other keys
    SNAPSHOT = "snapshot"
    FUNDING_RATE = "fundingRate"
    ESTIMATED_RATE = "estimatedRate"
    MARK_PRICE = "markPrice"
    INDEX_PRICE = "indexPrice"

    CONFIG_FILENAME = "config.yaml"
    CONFIG_ENV = "CONFIG"

    HANDLE_QUOTE = "handle_quote"
    HANDLE_INVENTORY = "handle_inventory"

    SUBSCRIPTION = "subscription"
    BOT = "bot"
    CONDITIONS = "conditions"
    FN = "fn"
    TAG = "tag"
    ACTION = "action"
    PARAMS = "params"
    PAUSE = "pause"
    LIQUIDATION = "liquidation"
    SYMBOL = "symbol"
    SYMBOLS = "symbols"
    EXCHANGE = "exchange"
    HOLD = "hold"
    SPREAD = "spread"
    TICK = "tick"
    GAP = "gap"
    VALUE = "value"
    MIN = "min"
    MAX = "max"
    QTY = "qty"
    FORCE = "force"
    HYSTERESIS = "hysteresis"

    TYPE = "type"

    REQUIRED = [SYMBOL, HOLD, SPREAD]

    ########## RabbitMQ Keys
    RABBIT_MQ = "rabbit"

    ########## Hazelcast Keys
    HAZELCAST = "hazelcast"
    PAYLOAD = "payload"

    ########## Influx Keys
    INFLUX_DB = "influx"
    HISTORY_DB = "history"
    DATABASE = "database"
    TABLE = "table"
    HOST = "host"
    PORT = "port"
    USERNAME = "username"
    PASSWORD = "password"
    MEASUREMENT = "measurement"

    STOPLOSS_COEFF = "stoploss_coeff"

    TRAILING_PROFIT = "trailing_profit"

    STOPLOSS_TRAILING_PROFIT = "stoploss_trailing_profit"

    FIRST_LIQUIDATION = "first_liquidation"
    SECOND_LIQUIDATION = "second_liquidation"

    PARTIAL_LIQUIDATION = "partial_liquidation"
    ATR = "atr"
    SHARE = "share"

    PCT = "pct"

    COEFF = "coeff"
    BUY = "buy"
    SELL = "sell"
    BUY_ID = "buy_id"
    SELL_ID = "sell_id"
    DISTANCE = "distance"
    WAS_UPDATE = "was_update"

    LONG = "long"
    SHORT = "short"
    UP = "up"
    DOWN = "down"

    MIDPOINT = "midpoint"
    LTP = "ltp"

    MODE = "mode"
    MODE_EMPTY = "empty"
    MODE_INVENTORY = "inventory"
    MODE_LIQUIDATION = "liquidation"
    MODE_HALT = "halt"
    TIMESTAMP = "timestamp"

    LOCK = "lock"
    STOP_AFTER = "stop_after"

    ########## Request Methods
    POST = "POST"
    GET = "GET"
    DELETE = "DELETE"

    STATUS = "status"

    INVENTORY = "inventory"

    PRICE = "price"

    COMMISSION = "commission"

    REALIZED_PNL = "realizedPnl"

    ESTIMATE_PNL = "estimatePnl"

    FEE = "fee"

    STOPLOSS = "stoploss"

    TAKE_PROFIT = "take_profit"

    BREAK_PRICE = "break_price"

    PENDING = "pending"

    OFFSET = "offset"

    ZERO = "zero"

    HALF = "half"

    ORDER_ID = "order_id"

    PORTFOLIO = "portfolio"
    ENTRY = "entry"

    EVENT = "event"
    LEVEL = "level"
    MESSAGE = "message"
    STATE = "state"

    ########## Stoploss States
    STATE_NORMAL = "normal"
    STATE_FIRST_HIT = "first_hit"
    STATE_SECOND_HIT = "second_hit"
    STATE_STOP_QUOTING = "stop_quoting"

    ########## Conditions parameters :: Pauses
    HIGH_ABS_SPREAD_PAUSE = "high_abs_spread_pause"
    HIGH_RATIO_SPREAD_PAUSE = "high_ratio_spread_pause"
    HIGH_LATENCY_PAUSE = "high_latency_pause"
    HIGH_ALLOCATION_PAUSE = "high_allocation_pause"
    HIGH_API_PAUSE = "high_api_pause"
    HIGH_LOSSES_PAUSE = "high_losses_pause"
    HIGH_ATR_PAUSE = "high_atr_pause"

    ########## Conditions parameters :: Values
    MAX_ALLOCATION_COEFF = "max_allocation_coeff"
    MAX_ABS_SPREAD = "max_abs_spread"
    MAX_LATENCY = "max_latency"
    MAX_RATIO_SPREAD = "max_ratio_spread"
    MAX_SPREAD_COUNT = "max_spread_count"
    MAX_ATR = "max_atr"

    ########## Hedging algo
    HEDGE = "hedge"
    MAX_QTY = "max_qty"
    MAX_PCT = "max_pct"
    MAX_INVENTORY = "max_inventory"
    THRESHOLD = "threshold"
    SIDE = "side"
    DIRECTION = "direction"
    SOURCE = "source"

    ########## Delta algo
    INTERVAL = "interval"
    SECONDARY = "secondary"
    DELTA = "delta"
    FORMULA = "formula"

    ########## Warming Up engine
    WARMING_UP = "warming_up"

    ########## Momentum Algo
    SCHEMA = "schema"
    DEQUE = "deque"

    ########## Global constants
    E = 1e-9
    ED = Decimal(1e-9)

    PERCENT = 0.01
    PERCENTD = Decimal("0.01")

    ONE_MS = 1_000_000
    ONE_SECOND = ONE_MS * 1_000
    ONE_MINUTE = ONE_SECOND * 60
    ONE_HOUR = ONE_MINUTE * 60
    ONE_DAY = ONE_HOUR * 24

    POSITIVE = "positive"
    NEGATIVE = "negative"

    RATIO = "ratio"
    MAX_RATIO = "max_ratio"

    SCALE = "scale"

    STOP = "stop"

    SINGLE = "single"

    MARKET = "market"
    LIMIT = "limit"
    IMPACT = "impact"
    USD = "usd"

    SIMULATION = "simulation"
    START_TIME = "start_time"
    END_TIME = "end_time"

    THORCHAIN = "thorchain"
    API = "api"
    ADDRESS = "address"
    PRIVATE_KEY = "private_key"
    CAPITAL = "capital"

    LOW_THRESHOLD = "low_threshold"
    HIGH_THRESHOLD = "high_threshold"

    NONE = ""
    DEFAULT = "default"

    LIVE = "live"
    MIN_ROC = "min_roc"


class LEVEL:
    TRACE = "trace"  # light blue

    DEBUG = "debug"  # blue

    INFO = "info"  # gray

    SUCCESS = "success"  # green

    WARNING = "warning"  # yellow

    ERROR = "error"  # red

    CRITICAL = "critical"  # purple


MAX_BATCH = 500

FLUSH_EVERY = KEY.ONE_SECOND

MONTH_MAP = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}
