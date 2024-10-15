## Thorchain Arbitrage Events and Questions

### Case 1

Lets say we what use arbitrage opportunity for BNB

We have thorchain BNB.BNB pool with 

  - runeDepth = 25_000_000_000
  
  - assetdepth = 1_000_000_000
  
Which gives us BNB price in RUNE = 25. 

Which means we can send 26 (+1 RUNE as commission) to Thorchain and receive 1 BNB (without transaction cost etc which 
are significantly less than 1 RUNE)

ALSO:

on DEX we have RUNEBNB market (RUNE-B1A_BNB), where we can sell RUNE and get BNB.

Lets say 
  
  -  current Best Bid = 0.0392156  (1 BNB ≈ 25.5 RUNE)
  -  current Best Ask = 0.0408163  (1 BNB ≈ 24.5 RUNE)
  
For DEX we can sell 10 RUNE with MARKET order and get 0.392156 BNB (without commission)

`BNB = RUNE * BestBid`


In a same time for Thorchain:

`BNB = (RUNE - 1) / 25` we will get 0.36 BNB, which means that DEX swap more profitable for 10 RUNE transaction

***

**My understanding is that we have to calculate target PNL (compare to DEX Market order)
 for current Thorchain ratio AND our capital; Swap only when target PNL > 1% (or something)**
 
#### Is it correct?
 
***

### Case 2

What we have to do with BNB after `Case 1`?

Our idea with `Case 1` is to buy cheaper BNB on Thorchain, when RUNE on Thorchain is overpriced (than DEX). But 
Thorchain market aim to be equal to DEX. Most likely BNB could not be significant cheaper for a long time.

#### Question: Dont we have to buy back RUNE on DEX, once we sold them to BNB with a good price?

**Example:**

 - runeDepth = 25_000_000_000
 
 - assetDepth = 1_050_000_000
 
 - Thorchain BNB price in RUNE ≈ 23.8095 
 
 - If we swap 100 Rune on Dex we will get ≈3.92156 BNB
 
 - If we swap 100 Rune on Thorchain we will get 4.158 BNB, which we can use to **buy** RUNE using Market 
 order and get ≈101.871 RUNE ==> ROC ≈1%
 
#### Is it correct?
