## Execution Design

Normally code designed to run *every 1 minute* using `cronjob` on `tokyo-one` ec2 instance

```
crontab -e
```

Actually that cronjob calling `~/dev/arbitrage.sh` script that running arbitrage procedure with given parameters

NOTE: Wy we are using cronjob: It help us to make process more stable. No mattter what happens, new process 
will check everything and will do a job

NOTE: Why we are running every minute: With DEX operations we have too high chance to be blocked fo few minutes 
because of too freq. requests. Also we are not really interesting for short arbitrage "spikes": because of
bepswap and transfers delays we are more interesting in long-term arbitrage opportunity  

For each arbitrage run we have to logs:

 - in a `log` folder we have `json` report similar with database one
 
 - in a `stdout` folder we have `stdout` and `stderr` stream dump for each run. It could help us to 
 track any kind of errors


## Arbitrage cases


For each run we are creating report for ALL arbitrage cases that are possible with given pool for
 BNB network through BNB product.
 
 Basically we have 2 variants:
 
  1.  
      - Buy some coins A on CEX exchange using BNB (ask price)
  
      - Move coins A to DEX
  
      - Swap A to BNB using Bepswap (using asset/rune depth and swap commission)
  
      - Move BNB back to CEX
  
  2. 

      - Swap some BNB to coins A on DEX using Bepswap (using asset/rune depth and swap commission)
  
      - Move them to CEX
  
      - Sell coins A on CEX and get some BNB (bid price)
  
      - Move BNB back to DEX

  For each case we have `ROC = "BNB we use at step (1)" / "BNB we get at step (4)" - 1`

  We applying that calculations using different swap capital (in BNB) from `capital` (settings) down to $500
  (CAPITAL_MIN constant in tools/arbitrage_proof/lib/swap.py) with step $100 (CAPITAL_STEP constant in 
  tools/arbitrage_proof/lib/swap.py) with a little bit (1/4 of CAPITAL_STEP) randomization
  
  After all calcualtions we have LIST of cases with variations of
  
    - product
    
    - capital
     
    - case 1 or 2
    
## What we are doing with cases

  - For each product we are sort capital and cases by target ROC and choose top (best) one
  
  - We creating list of cases where each product has the best ROC (best capital-case combination)
  
  Note: We are trying to apply different capital because bigger capital could have bigger 
  slippage, but lower capital has the same commission (1 RUNE) which also decrease ROC
  
  In turn, we cant guarantee for each case same actual ROC. It could be lower because of
  swap queue and orderbook depth. So, when we are trying to implement 1% case and actually 
  getting less -- our ROC could be 0.5% which is > 0. In a same condition for target ROC
  0.4% our actaul ROC could became -0.1% and we will lost some money
  
  
## Withdraw amount issue

When we making arbitrage swaps, we have to constantly move money from CEX to DEX. For DEX 
we have no withdraw limits, but for CEX it equal 2 BTC/24h for unverified accounts.

Also it seems like that 24h not rolling and not cleaning at 00:00 UTC: Binance blocks 
withdraw a little longer

Currently we have implemented multiply accounts feature:

  - When we have several accounts in configuration file, BALANCE became SUM of all BNB balances,
  also with withdraw amount. Everytime before arbitrage we are choosing account which
  has lowest withdraw amount for last 24h. If this amount less than 80% of withdraw limits --
  we are using that account fro arbitrage. If no accounts has 24h-withdraw less than
  80% of daily withdrawal -- arbitrage is forbidden
  
  Note: Binance has no API endpoint to get current 24h withdraw amount in BTC. So, we are
  sum all withdraw qty in coins for last 24h and converting tham to BTC using current (latest)
  rate. Binance not giving us details how execalty they caclulate withdraw amount in BTC
  so this value is estimate only. This is why we are using threshold as 80% to stop using 
  account for arbitrage  