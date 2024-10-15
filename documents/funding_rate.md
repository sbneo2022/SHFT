# Math basics

# Funding rate automation

## Funding Rate Update Algo

1. Using `/fapi/v1/premiumIndex` endpoint load `lastFundingRate` and `nextFundingTime` 
for all Binance Futures products into dict where `symbol` is a key

2. Using `/fapi/v1/ticker/24hr` endpoint load 24h `quoteVolume` for all assets into
dict where `symbol` is a key

3. Create list of dict where each item has Symbol, Funding Rate, Volume and 
Volume-Weighted Funding Rate:

   - `N`: number of Binance products
   - `Sum`: Sum of 24h Volume for all products
   - `fundingRate`: Funding Rate of each product
   - `Volume`: 24h-Vol
   - `VWFR` = `N` * `fundingRate` * `Volume` / `Sum`
   
4. Sort List by `fundingRate` field

5. Save all items to `log` folder with name as `%Y%m%d-%H%M%S.json`

6. Get all products with `fundingRate` > `Threshold`. `Threshold` is command-line arg with
0.0001 (1bs) as default value

7. Print Top `N` (or less: using `threshold`) symbol names to `stdout`. This names could be
used by Bash script fo scheduled task

## Funding Rate Automation

1. Every 8h (at 00:00, 08:00 and 16:00 UTC) we are running Bash script using cronjob

2. This script running Funding Rate update algo (with N = 5 --> top 5 products) and used
stdout list as list to run bots in separate screens

3. Each bot running with `--add '{"action":"single"}'` key (which adding same key 
into startup config). This action means that bot safe exit if any Futures inventory found. 
It helps to avoid several bots with same products

# Funding Rate Bot Behavoiur

## Execution mode: `action` Key

Funding Rate Bot could run in 4 regimes:

1. `default`: _If_ Futures inventry non-zero --> Scale-In Spot inventory (and Futures will follow); 
_Else_ just monitor `fundingRate` and write unrealizedPnl log

2. `single`: _If_ Futures inventry non-zero --> Scale-In Spot inventory (and Futures will follow); 
_Else_ safe exit bot

3. `liquidation`: Set Target Spot inventory to 0 and start scale-out. Futures inventory will 
ot Spot

4. `scale`: Set new Target spot inventory using `max_inventory` or `usd` key from config. `usd`
key has higher priority than `max_inventory`. NOTE: for `usd` key we are scaling using *current*
midpoint price. So, Target inventory could be different and could cause buy or sell orders even
with same config file

We can set regime as constant in `yaml` file adding key (for example):

```
action: single
```  

or adding `--add '{"action":"liquidation"}'` to command-line args

## General Behaviour

1. After bot started we have some `warming_up` time. Default setting for `funding_rate` 
bot is 10 seconds. We need this time because websocket userdata subscriptions are asynchronous.

2. After warming-up time we are making operation mode according to `action`

3. Every second after warming-up time we are checking Spot inventory. If it changes -- are 
LOCKING Spot Limit orders and posting MARKET order for Futures. 
  
  - For `liquidation` mode we can only DECREASE Futures inventory. We need this condition
  to correct handling unhadged inventory (because of out of margin). Skip other tasks  

  - If no Marker orders in Queue -- UNLOCK Limit orders
  
  - Track `unrealizedPnl` to database
  
4. For every `fundingRate` websocket update: if `fundingRate` < `threshold`: 

  - Set `liquidation` mode 
  
  - Set target Spot inventory to 0 using Limit orders
  
5. If we are in `liquidation` mode and current Futures inventory is 0: Safe exit.

## Scaling In-Out using Limit orders

### Module settings and default values

- `limit.impact: 0.05`  # 0.05 -> 5%; we are limit qty of each Limit order by 5% of Top5 
asks (for Sell order) or 5% of Top5 bids (for Buy order)

- `limit.pause: 10`  # How many seconds we are holding Limit order in orderbook. After this
time we are canceling Limit order and posting new with new qty.

### General behaviour

```
make_qty_limit(self, qty: Union[int, Decimal], target: str = KEY.DEFAULT,
                     tick: Optional[int] = None, lock: bool = False)
```

This function adding new Limit Task to queue and running first "step"

- `qty`: TARGET account qty

- `target`: Exchange name where we want to set target qty. Now "Funding Rate" bot  operate
with `default` (`KEY.DEFAULT`) exchange (Futures from default config) and `hedge` (`KEY.HEDGE`)
exchange (Spot from default settings)

- `tick`: when this arg is not None - we are override tick distance from config file for
given task

- `lock`: when it True we are checking `self._lock_state` before posting new Limit order. 
Do not post till if became `False`. When this arg if False -- `self._lock_state` are ignored  

Once we adding new task to queue -- we are running first step

### How we operate every step

Every second we are running `_handle_next_limit_step` method

1. We are finding `delta` = `target inventory` - `current inventory` 

2. If `delta` almost 0 --> delete current Task and return. We finished current task

3. Return if `limit.pause` time is not gone by. Else cancel current open Limit order

4. Find new `base_price`: `bid` for `Buy` orders, `ask` for `Sell` orders

5. Add or substract `limit.tick` ticks to/from `base_price`

6. Set `liquidation` flag: if abs(target) < abs(current).
  
   - for `liquidation` procedure we should set special flag for Binance orders
   
   - When we liquidate we should make sure our order qty (after rounding) will not exceed 
   current inventory. It could happens for Spot when commission are substract from 
   inventory

7. Find maximum orederbook impact using Average Bid/Ask Volume. We are using Ask volume for
Sell orders and Bid volume for Buy orders. Default length of orderbook averaging is 10 items
(for Binance we have around 10 updates/second). 

**Note: We can change this parameter using `deque: N` key in config. This will be affected to 
all modules that are using TopOrderbookImbalace (Ask/Bid Volume and Ratio)**  

8. Make order Qty = min(Order Qty, Max Impact) 
 
9. Apply `minQty` rules to order. If resulting Qty is 0 --> delete task and exit. This means 
we cant make more precise step with current product

10. Post limit order and save `orderId`


## Scaling In-Out using Market orders

### Module settings and default values

- `market.impact: 0.05`  # 0.05 -> 5%; we are limit qty of each Limit order by 5% of Top5 
asks (for Sell order) or 5% of Top5 bids (for Buy order)

- `market.pause: 1`  # How many seconds we are waiting between Market orders.

### General behaviour

```
make_qty_market(self, qty: Union[int, Decimal], target: str = KEY.DEFAULT,
                     impact: Optional[Decimal] = None)
```

This function adding new Market Task to queue and running first "step"

- `qty`: TARGET account qty

- `target`: Exchange name where we want to set target qty. Now "Funding Rate" bot  operate
with `default` (`KEY.DEFAULT`) exchange (Futures from default config) and `hedge` (`KEY.HEDGE`)
exchange (Spot from default settings)

- `impact`: when this arg is not None - we are override impact from config file for
given task

Once we adding new task to queue -- we are running first step

### How we operate every step

Every N (`market.pause`) second (we are running `_handle_next_market_step` method

1. For first step for new task we are finding 
`delta` = `target inventory` - `current inventory` 

  - If `delta` almost 0 --> delete current Task and return. We finished current task
  
  - Set `liquidation` flag: if abs(target) < abs(current).

2. Find maximum orederbook impact using Average Bid/Ask Volume. We are using Ask volume for
Sell orders and Bid volume for Buy orders and multiplying by `impact`

3. Make order Qty = min(Order Qty, Max Impact) 

4. Apply `minQty` rules to order. If resulting Qty is 0 --> delete task and exit. This means 
we cant make more precise step with current product

5. Post limit order and save `orderId`