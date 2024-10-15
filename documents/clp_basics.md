# CLP Bot Basics

***

Note: Current description has only few implementations details because:

 - Probably current python version is not the best
 
 - Different language could have better practices and solutions
 
***

## Source data

Websocket streams of TopBook, Trades and Klines

Note 1: We are trying to adjust out local and Binance time for correct latency 
calculations 

Note 2: Low latency is very important here so we running websocket process on 
separate core (not multythreading but multyprocessing schema)

Note 3: For latency decrease we are not using side services like Redis for data 
exchange, only shared memory or something like that

Note 4: Dont forgot to follow all Binance rules of websocket operations: like 
"every 24h restart" etc

1. Websocket stream of Best Ask/Bit Price and Qty

- For every event we caclulate latency of data

- Every event should be saved async to InfluxDb

2. Websocket stream of Trades

- Currently we just saving (async) it to InfluxDb as Reference. But ready to use in algo

3. Websocket stream of 1min Klines

- Used to have N-hours moving window for ATR caclulations
    

## CLP Bot operations

For liquidity providing we handling 2 types of data: 

 1. Klines (Candles). 
 
 - Every minute we have new finished candle, and we update moving window with it
 
 - For new window we calculate 1h ATR (as % to latest Close price)
 
 - We set new Stoploss distance as 8 * ATR
 
 NOTE: We cant provide liquidity until we have first ATR (and stoploss distance) 
 
 
 2. Best Ask/bid (Most important part)
 
    2.1 For each ask/bid data change first we handle new Buy/Sell quotes (replace/not) 
    
    2.2. If we have some  inventory -- we handle inventory operations
    
### Handle Quotes

1. We have to check some conditions -- when we have to stop (pause) quoting. 

 - For each pause we have to CANCEL all open orders ASAP
 
 - We holding in memory 300 (parameter!) last **spread** `2*(ask-bid)/(ask+bid)` values
 to find `average_spread`. 
 
 - If current **spread** N times (currently 200%) more than average - we pause for 3s
 
 - if average spread or latest spread > 0.3% we pause for 6s
 
 - if ask/bid event latence > 0.5s we pause for 6s (thats means something wrong with
  network and market data are not relevant)
  
 - if current inventory > LIMIT we pause for 6s
 
 2. If all conditions are ok, we going next
 
 In general we could have N spread levels, but currently we r working with INNER and
 OUTER spread. As a first cut lets say INNER spread = 1%, OUTER spread = 2%
 
 Now our math for inner spread should looks like:
 
 - When bot init we finding spread value with some gap, lets sat 5%. We are trying to set 
 spread a little bit smaller than target 1%
 
     used_spread = spread * (1 - gap) // 0.01 * (1 - 0.05) = 0.0095
     
     And we will set Buy/Sell levels simmetrically from midpoint
     
     spread_coeff = used_spread / 2
 
 - Now "Live" we finding "midpoint"
 
     midpoint = (ask + bid) / 2
 
 - And Buy/Sell levels
 
     buy = midpoint * (1 - spread_coeff)
     sell = midpoint * (1 + spread_coeff)
 
 - **Holding time behaviour** For Binance qualification we should have our order in Orderbook 
 more than 2s. We r using T = 2.1s
 
     Actually we can save API calls and do not change Buy/Sell open orders for EVERY 
     bid/ask ticks, but only react to some significant changes. 
     
     Lets name is as "Hysteresis" with 5% for Inner spread (Outer spread could have different value
     because if far away from ask/bid, we can change it not so often)
     
     But from other hand, and we see that after 1s ask/bid price too close to fill our order,
     we can try to CANCEL it and save fron Inventory. Lets name this threshold as "Force"
     and make 50% for Inner spread
     
     Now this is our trigger to replace Buy/Sell orders:
     
     "Force" threshold INSIDE holding period and "Histeresis" -- outside.
     
     We r applying these threshold to "Distance" which caclulated for each new ask/bid if
     "Force" is present, or for each ask/bid AFTER holdeing time if no "Force" present 
     
     Note: For FIRST levels we have how "Current" Buy/Sell prices --> No distance --> We 
     just set new Buy/Sell levels
     
     distance_buy = (bid - current_buy) / original_buy_distance  
     
     distance_sell = (ask - current_sell) / original_sell_distance
     
     If BOTH distance > (1 - threshold (Force/Hysteresis)) ---> we DO NOT replace orders 
     and just hold them evenn after target 2.1s time
 
- If any distance < threshold ---> we have to replace Buy/Sell orders

    We have to round our levels with Binance rules
    
    For Buy we round UP (using tick size), for Sell -- Down
    
    We Post **Async** 2 LIMIT orders and one BULK CANCEL orders for previous Buy/Sell
    
    Note: On Exchange adapter level we handle "None" for Cancel order id, also async
    issues when we trying to cancel order that not posted yet
    
    We remember new Buy/Sell levels 
    
    We remember new Buy/Sell OrdersId
    
    We remember "Original" Buy/Sell Distance as 
   
      - original_buy_distance =abs(Buy - bid)
      - original_sell_distance =abs(Sell - ask)
      
    We log eveything (async) to InfluxDb
    
    Save time that will be used for "Holding Time Calculations"
    
    
### Handle Inventory

Every time we have inventory we trying to liquidate it with Tailing Stoploss Schema
 (Zero price adjusted)
 
#### What does "Zero price adjusted" means

We have some constant (parameter) Minimal Stoploss Distance, lets say 0.1%

Lets say we r LONG

If current (bid for LONG) price > "entry" + 2 * commission + 0.1% --> we set NEW 
stoploss distance as 0.1%

Which means that we will pe positive in any case

We will make only 0.1% less money than "pick" price

But chance to "exit" also became higher

#### Trailing stoploss steps

For each new ask/bid we calculate new Stoploss price

NOTE: For FIRST Stoploss price we r usinig Entry price, not current

Lets say for LONG:

stoploss_price =  new_price * (1 - stoploss_distance)

Now new_stoploss_price = max(current_stoploss_price, stoploss_price)

If new_stoploss_price != current_stoploss_price --> We "save" new_stoploss_price

Now if new_stoploss_price > price (bid for LONG) --> we LIQUIDATE All inventory 
with MARKET order

Note: If inventory CHANGES --> Entry price also changes --> we RESET stoploss_price 