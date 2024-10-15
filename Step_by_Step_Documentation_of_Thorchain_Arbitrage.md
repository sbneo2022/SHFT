Lets first document the process i want on grafana

Grafana plots:
1. Plot the asset depth and the rune depth on grafana for every asset
2. Calculate the asset price in runes = asset depth/rune depth
3. Calculate the market price of the asset denominated in rune
4. Make the plots of 2 and 3 in the same panel (One on the left y axis, and the another in the right z axis)
5. Make the market delta plot for the asset = (Pool price of the asset - Dex price of the asset)/(Pool price of the asset)

Lets calculate the process of arbitrage in the backend but plot it on grafana

1. At any moment --> instantaneously you will have the asset price in RUNE (step 2)
2. Calculate the delta for this asset price (step 5)
3. Our objective is to reduce the delta by 50%

Show this example for the bnb pool using a sandbox

Example :

print the following 

X = Rune depth 
Y = asset depth

1. asset price = Y/X
2. calculate the market delta = (asset price - binance dex mid pt)/asset price 

Now we will only target to do 20% of the trade at a time

3. so the delta = (binance mid pt (Market price) - asset price)

Is 3 positive or negative ??

For 3 (take that sign in the calculation of the trade size y)

4. so the trade size = (delta * rune depth * asset depth)/(5 * asset depth) # remember its 20% at one time

5. so the output = (trade size * rune depth * asset depth)/(trade size + asset depth)^2

6. Now update the pool depth parameters : New Asset depth = Old Asset depth + trade size ; Rune depth = Rune Asset depth + output

7. Calculate the new asset price = Y/X ---> this should be closer to the market price of the asset





