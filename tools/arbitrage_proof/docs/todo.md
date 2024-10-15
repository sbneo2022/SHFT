## Arbitrage Bot TODO

1. Now when we starting Arbitrage process, we doing it single-thread and we cant start new
Arbitrage till current is end
    
    There are several reasons for this schema:
    
    1. DEX Api blocking. Instead of API call limit for CEX, with DEX we could be blocked
    for several minutes by DEX Cloudfront because of too frequent request. For multy-thread
    arbitrage we could be blocked (by IP address) when two process asking DEX with microsecond
    delay
    
    2. For CEX Spot Excahnge the only way I found to find how much BNB we were used to by coins
    is to make wallet snapshot BEFORE and AFTER Buy/Sell. If we run several arbitrage 
    processes we will lost this information
    
    3. When we finding some arbitrage case it could be valid only for some target capital. Lets 
    say we want to swap $1000 first. If in a secound we will run same swap in different process,
    it will see OLD asset/rune depth because first swap is not finished yet (in queue). But it
    will be already started and could be negative, because all profit will be taken by first 
    process. Same issue with CEX orderbook depth and price 
    
    But anyway, its not good to loose arbitrage opportunity. We have to create schema that
    let us to handle several arbitrage cases. Probably it should be server-side code that 
    constantly looking for opportunity and several child processes that trying to implement 
    them. But child processes should be running under server supervising
    
2. We have to add feature that take out daily revenue to some separate wallet, so operation
wallet should have only operational capital. As option revenue could be converted in stablecoins

3. Now we operate with BEP2 chain only. But there could be some arbitrage opportunity woth
same logig using Thorchain or ETH
 