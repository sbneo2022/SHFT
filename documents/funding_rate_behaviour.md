## Funding Rate Behaviour Details

***

**Version 5/26/2021**

***

### Bot can start with 4 Actions:

- "action": "default" `Note: this action is default without additional keys`

  1. Check FUTURES (default) inventory
  
  2. If DEFAULT inventory is not ZERO --> continue in HALT mode
  
  3. Else add HEDGE task: increase (change) SPOT inventory to current target and set mode INVENTORY
  
      - Note: If target inventory has been set with USD allocation, we are using current price to find target QTY
      

- "action": "single" `Note: we can use this action with key --add '{"action": "single"}'`

  1. Similar with "default" but EXIT if any FUTURES inventory found
  
  2. Could be used in scripts
  
  
- "action": "scale" `Note: we can use this action with key --add '{"action": "scale"}'`

  1. Find new QTY using latest price and USD allocation
  
  2. Set HEDGE task and continue with mode INVENTORY


- "action": "liquidation" `Note: we can use this action with key --add '{"action": "liquidation"}'`

  1. Set LIQUIDATION mode and continue
  
### Operation mode

1. HALT

  - FUTURES inventory do NOT follow to the SPOT
  
  - Constantly monitor FUNDING RATE
  
  - Liquidate both (SPOT and FUTURES) if FUNDING RATE below threshold AND both sides are equl
  
  - Equal means `abs(futures / spot) - 1 < 0.0001` (difference between SPOT and FUTURES less than 1bps)
  
  - Note: In HALT mode FUTURES inventory is not follow to SPOT: we can change SPOT safely now
  
  - Note: But inventory will NOT be liquidated with FUNDING RATE threshold if FUTURES QTY != SPOT QTY. We 
  should make QTY equal OR restart bot with LIQUIDATION action 
  

2. INVENTORY

  - For each SPOT account update we:
   
    - set FUTURES target qty equal -SPOT (add new task to futures tasks list)
    
    - Block SPOT limit order
    
    - Unblock SPOT limit orders when FUTURES task is done (no tasks in list)
  
  - If SPOT task is empty: wait 1 minute and set mode HALT
  
  - Note: In inventory mode we are do not watch for funding rate threshold crossing
  
  
3. LIQUIDATION

  - Add SPOT task "Make QTY zero"
  
  - For each SPOT account update behaviour equal to INVENTORY mode, but we can only INCREASE FUTURES inventory.
  We have this case if for some reason we running bot with LIQUIDATION action, but portfolio is unhedged. In this
  case we are first decrease SPOT inventory (make equal FUTURES qty), then will start increase (decrease absolute
  value) of FUTURES inventory.
  
  - If FUTURES inventory is zero --> stop the bot. Because FUTURES always follow SPOT --> this means that SPOT 
  also already is ZERO 
  
