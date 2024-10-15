### Custom Order Id Agreement

***

1. I guess its better to use Custom orderId when we Post new Order

   - We can filter open orders by source
  
   - We can separate them from Web Orders
  
   - We get orderId instantly -- we dont have to wait while er gat Exchange Reply
  
2. Naming Theses

   - Id should be a string
  
   - No more than 32 symbols
  
   - Some symbols are prohibited: '/', ':', '*' etc
  
   - We should understand WHO post this order
  
   - We should understand WHEN we post this order
  
3. Solution
   - Get some project ID that will identify as string
  
     - Log Series Name in database **or**
    
     - Some config as JSON string
    
     - Or given name
    
     - Dont forgot to use traded SYMBOL
    
     - This function should be common for whole project 
    
   - Solve CRC32 of that string and write as HEX
   
   - Get UTC time **and**
   
   - Make string as "YYYYmmdd.HHMMSS.FFFFFF"
   
      - It will help us to understand time without side-tools
     
   - Join CRC32 and Time with separator '-'
   
4. Example

   - Lets say we write to results to "clp_bot" table and trade RUNEUSDT
   
   - Project string = "clp_botRUNEUSDT" 
   
   - CRC32 = "fa2d9746"
   
   - UTC time when we POST = 2020-12-11 12:33:34.950061
   
   - orderId = "fa2d9746-20201211.123334.950061"
   
5. Summary

   - We can find our orders easily because we know CRC32 and can split 
   orderId by '-'
   
   - We can see from logs without additional tools/data WHEN exactly order 
   was created
   
   - And we know (and can save and can use to CANCEL) orderId **before** 
   Exchange reply
   
       
