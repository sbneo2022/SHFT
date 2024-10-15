## Project Structure 

### `\lib`

This folder contains various abstract classes, implementations
and helpers

**General Timer Note**

Most classes and helpers are used AbstractTimer object. Normally
in live execution it returns current time/timestamp and implementing
`Sleep` but for backtest we can use virtual timer, that handle
virtual time.

In general no helper/class should not use real "live" time and
Sleep but use AbstractTimer methods only. 

**Helpers**

1. `async_ejector.py`

Create new thread and write asynchronously to database fields
or log message

  - LogAsyncEjector
  
    Constructor receive:
      - AbstractDatabase class instance
      - Abstract Timer class instance
      - `data`: dict with any fields
      - `message`: str will be added to `data` 
      - `level`: str will be added to `data` 
      
    Behaviour:
      - In new thread we encoding data to InfluxDb string
        and writing to database

  - FieldsAsyncEjector
  
    Constructor receive:
      - AbstractDatabase class instance
      - Abstract Timer class instance
      - kwargs: any fields 
      
    Behaviour:
      - In new thread we are encoding kwarg fields to InfluxDb string
        and writing to database

2. `constants.py`

In order to decrease chance of error we trying to use constants as often
as possible instead of some text strings

Most constants are in `constants.py` under `KEY` class

Also this file contains some OMS-messages for ORDER_TYPE etc

Note: This file shold not has any significant values

3. `defaults.py`    

This file contains default values that will be used when no data present in config
file etc

Note: Should be used carefully because can cause a hidden error

4. `helpers.py`

Various helpers:

- Simple `sign` function to aviod using numpy
- Class loader "using filename"
- Class loader "using classname and parent class"
- Json serializer/deserializer with Decimal/Datetime support

5. `init.py`

Functions to load yaml configs and merging them. Function "init_service" has rules
"How we joining config files" and return final dict with all settings

6. `ping.py`

Function `get_binance_lag` return timedelta of LOCAL time and BINANCE time PLUS 1/2
of ping to `fapi.binance.com`

7. `watchdog.py`

Class Watchdog has handlers for system shutdown.

Behaviour:

Class constructor register hisself with `atexit` and as SIGINT lister.
Also we can add additional functions that will be called at program exit with
`addHandler` method.

So, in all cases:
 - normal exit
 - any error exit
 - Keyboard break
 
all "exit" functions will be executed

This class help bots to clear inventory/open orders in all exit cases 

#### Classes
***

**General Note**:

Most classes constructors receive:

 - config: dict
 - factory: AbstractFactory
 - timer: AbstractTimer
 
as arguments. It helps to make code clear and let create all modules they need

Only AbstractTimer should be **single** across all product to handle correct time

#### `\lib\database`

This the place for database connectors. Currently we are support 
InluxDb only as 'prod' version. We can add TimescaleDb later

Also we have two possible adapters:

 - FakeDb: We write all data to screen instead of database
 - NoDb: We just skip all database data
 
 Usually we can use these adapters to debug database interactions (FakeDb) ot to
 test other parts when we do not case od log/databse
 
 Behaviour:
 
 In order to increase performance we encode database record to string using `Encode`
 method. Then we can collect them to list and pass as "bulk" to `writeEncoded` method.
 
 #### `\lib\factory`
 
 This object returns next class types (not instances!)
 
 - Vault: how we get keys/secrets/etc
 - Database: How we store data
 - Timer: Which timer should we use
 - Logger: Which logger should we use
 - State: How we read/save current application state
 
`AbstractFactory` constructor receive only `config`: dict but basically only "as general"
for future improvemets

Also this folder contains 3 implementation of AbstractFactory:

- LiveFactory: 
   - ConfigVault as Vault: get keys from config
   - InfluxDb as Database
   - LiveTimer as Timer
   - DbLogger as Logger: write all messages to console AND database
   - DbState as State: Save state to database (InfluxDb) as json field 

SandboxFactory
   - EnvVault as Vault: get keys from Environment variables
   - FakeDb as Database: write all data to stdout
   - LiveTimer as Timer
   - ConsoleLogger as Logger: write all messages to console only
   - MemoryState as State: Save state to memory only (no continue after restart)
   
CustomFactory
   - We can set custom classes in class Constructor
 
  
 #### `\lib\logger`
 
 Class AbstractLogger help to write log messages to screen or/and database/other 
destination.

It has follow methods:

trace, debug, info, success, warning, error, critical

Each method accept `message` as log message AND fields as `kwargs`. Additional filelds 
will be added as json string

This schema helps to write more machine-readable data to log message

`ConsoleLogger` class write all messages to console only

`DbLogger` class write all messages to console and database. Database operations are
 **async**
 
#### `\lib\state`

`AbstrastState` class instance should implement two methods:
 - `Push` with dict as argument
 - `Pop` that return dict
 
Every time we change our state we can "Push" it somewhere. When we run program again
we can "Pop" it back

We have 2 implementation of AbstractState:
  - DbState: write state to database 
  - MemoryState: hold state in memory only
  
#### `\lib\vault`

`AbstractVault` class instance should return key value using `Get` method

Possible keys are in `VAULT` class

We have 2 implementation of AbstractVault:
  - ConfigVault: Get key/secret from Config inside key with exchange name
  - EnvVault: Get key/secret from Environment variables. Note: We r using `uppercase` 
  of VAULT keys as Environment variables
  
TODO: Implement adapter to HashiCorp Vault system

#### `\lib\exchange`

`AbstractExchange` class instance should implement abstract Excahnge interactions. 
Currently we have only Binance adapter

This class provide basic operations like Post/Cancel orders, getPositions etc

    Note: All operations for single product only. Product should be under "symbol" key

    Note: Also we have to have key "excahnge" with exchange name. This name will be used
    as key for next parameters:
       - key
       - secret
       - rest_url


- isOnline: bool  Return False when we have some technical problems with exchange.
Currently for Binance this method return False when we are close to any API limits

- getBook: dict  Return dictionary with top book

- getBalance: dict Return dictionary with current account balance

- getTick: Decimal  Return min price tick of current product

- getMinQty: Decimal  Return min qty of current product

- getPositions: dict   Return dictionary with curretn open positions

- getCandles(start_timestamp: int, end_timestamp: int) -> Dict[str, deque]
Return dictionary with OHLCV keys and deque as value. Depth of deque (max_len) 
equal to start-end distance

- Post(qty: Decimal, price: Optional[Decimal] = None,  stopmarket: bool = False, wait=False) -> str
  - The only required parameter is `qty`. In this case it will be `MARKET` order
  - If `price` is passed order will be `LIMIT`
  - If `stopmarket` is True order will be CONDITIONAL MARKET
  - If `wait` is True Post return orderId when Exchange reply will be received. By
  default Post return orderId (str) without waiting of exchange reply
  
      NOTE: For MARKET order if exchange code is not 200 we are trying to send order again 3 
      times with increasing delay
  
 - PostList: Same as Post but with list of Orders as parameter. Return List of orderId
 
 - Cancel: 
   - Without arguments CANCEL all open orders
   - With one str argument CANCEL one order
   - With list of str arguments CANCEL list of orders
   
      NOTE: In case of "Order not found" it trying to repreat CANCEL 3 times with 
      increasing delay  


Note: Also here we have a function that return Exchange class from excahnge name.


#### `\lib\exchange`

 `AbstractStream` implement only one method: 'Run'. 
 
This method start process that handle websocket data and:
 - write log to AbstractDatabase
 - send messages to AbstractSupervisor Queue
 
### `\bot`
`AbstractBot` class instance implement event-based model. Class instance could 
implement next methods to handle events:

 - onTime: receive current timestamp every second& Could be used for delayed 
 operations and data watchdog (restart system in case of "no new data")
 
 - onAccount(price, qty): handle this method every time account changes
 
 - onOrderbook(...): handle this method every time we have new top book message
 
 - onTrade(...): handle this method every time we have new trade
 
 - onCandle(...): handle this method every time we have candle (every minute)
 
 The only required method is `Clean`: what we should do on "Exit" signal
 
 
 #### SandboxBot
 
 This bot designed to tests and just print all events as log messages
 
 #### CLP
 
 Base class for CLP bot
 


### `\scripts`

### `\yaml`

