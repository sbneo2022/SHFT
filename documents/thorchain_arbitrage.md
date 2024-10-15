## BNB Only Version

### Data source

1. For Binance Dex we are using websocket orderbook subscriptions
  Now we are using only best ask/bid, but technically we can use up to Level 200

2. We constantly have in the memory:
    
   - Current RUNE-BNB rate
   
3. Every second we are updating Thorchain details for choosen product (lets say BNB.BNB) 
    
   - runeDepth
    
   - assetDepth
  
  
### Arbitrage Opportuntity Math


Thorchain price in RUNE

`tpin = runeDepth / assetDepth`

**Arbitrage Schema #1:**

  1. Send N `Rune` to Pool
  
  2. Get M `BNB`
  
  3. Convert M `BNB` to K `Rune` using Market Order on DEX Exchange
  
  Our expectation is to get more Rune than N, taking account all fees
  
**Arbitrage Schema #2:**

  1. Send N `BNB` to Pool
  
  2. Get M `Rune`
  
  3. Convert M `Rune` to K `BNB` using Market Order on DEX Exchange
  
  Our expectation is to get more Bnb than N, taking account all fees

  
**How we are testing this idea***

Schema 1:

For each RUNE `capital` in [10, 100, 1000] we are calculating:

 - How much BNB we get from Pool: M = (`capital` - 1) / `tpin` 
 
 - How much we will get Rune on Dex using MARKET order: K = M / `Best Ask Price`
 
 - ROC = `How much we will receive` / `capital` - 1
 
 - Final formula: ROC = (`capital` - 1) / (`capital` * `tpin` * `best_ask_price`) - 1
 
 - We are writing results to InfluxDb as `rune_10`, `rune_100`, `rune_1000`
 

Schema 2:

For each BNB `capital` in [1, 10, 100] we are calculating:

 - How much RUNE we get from Pool: M = `capital` * `tpin` - 1 
 
 - How much we will get BNB on Dex using MARKET order: K = M * `Best Bid Price`
 
 - ROC = `How much we will receive` / `capital` - 1
 
 - Final formula: ROC = `Best Bid Price` * (`capital` * `tpin` - 1) / `capital` - 1
 
 - We are writing results to InfluxDb as `bnb_1`, `bnb_10`, `bnb_100`
 
  
General notes: 

 - We can make money when ROC is positive
 
 - This formula is not taking account DEX 0.000075BNB transaction fee (x2) 
 
 - This swaps are limited by Best Ask or Bit Qty
 
 - For big swaps we will have bigger slippage
 
Next steps:

 - Make formula general for assets other than BNB (Using additional DEX swap?)
 
 - We can try, lets say for Schema 1:
 
    - Every time we have profitable thorchain imbalance post DEX LIMIT order and hold it few seconds
 
    - When it got filled -- **make Thorchain swap**
    
    - If not --> replace IF imbalance still exists 

   