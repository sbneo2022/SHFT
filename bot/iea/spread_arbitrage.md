## Parameters

`high_threshold`: spread value used to open arbitrage process AND to flip positions

`low_threshold`: spread value used to flip positions

`direction`: +1 or -1 used to choose Long/Short direction for each exchange. Should be `-1`

## Step 1: Find midpoints

1. `binance_midpoint = (binance_ask_price + binance_bid_price) / 2`

2. `ftx_midpoint = (ftx_ask_price + ftx_bid_price) / 2`

3. `arbitrage_midpoint = (binance_mipoint + ftx_midpoint) / 2`

## Step 2: Find Spread

Note: Lets call Binance Exchange as `A` and FTX Exchange as `B` to make math general

`spread = (A_midpoint - B_midpoint) / arbitrage_midpoint`

## Case 1: We just start our bot and have no open positions

1. Wait for abs(`spread`) > `high_threshold`

2. Save initial spread value and open positions using follow schema:
 
  `A` exchange direction: `direction` * sign(`spread`)
  `B` exchange direction: -1 * `A` (opposite)
  
   **Example**
   
   `A` midpoint = 105; `B` midpoint = 100
   
   `spread` = (105 - 100) / 102.5 = 0.0487804878 ≈ 488 bps
   
   `direction` = -1
   
   sign(`spread`) = +1 --> we go `SHORT` for `A` and `LONG` for `B`
   
   **Later:**
   
   `A` midpoint = 82; `B` midpoint = 81
   
   `spread` = (82 - 81) / 81.5 = 0.01226993865 ≈ 123 bps

   We going to FLIP positions

   `A pnl` = -1 * (82 - 105) = +23 
  
   `B pnl` = +1 * (81 - 100) = -19 
   
   `Arbitrage Pnl` = `A pnl` + `B pnl` = 23 - 19 = 4 (minus commissions)
   
## Issues

1. Currently our spread and target pnl calculations based on midpoint, but actually we are 
using ask price for LONG order and bid price for LIQUIDATION, which decrease our pnl.

    Often asb/bid spread not so big, but we better to count it also


2. Right now we are working with one side spread only. Actually most products has "two-side"
spread: from +20bps to -20bps (as example). We should improve logic and use whole distance 
from +20 to -20 when it possible (currently we are using +20-0 or -20-0 spread)
