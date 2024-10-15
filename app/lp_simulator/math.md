## Liquidity providing math

```math
pool\_fee\_collected = 0.0017 \times transaction\_volume
\\
\\
share\_of\_pool = \frac{lp\_capital}{pool\_size}
\\
\\
lp\_revenue = share\_of\_pool \times pool\_fee\_collected
```


## Impermanent loss

```math
price_{t} = \frac{reserve^0_t}{reserve^1_t}
\\
\\
price\_change = \frac{price_{t1}}{price_{t0}}
\\
\\
iloss = 2 \times \frac{\sqrt{price\_change}}{1 + price\_change}) - 1
```

## Arb revenue
```math
c = \frac {k \times \left(1-f_c\right) }{ask} \times \left(1-f_{tc} \right ) \times \left(1-f_d \right )
\\
roc_{case1}=\frac { \left( 1-f_d \right)xy}{x+k\left( 1-f_d \right)}\times \left( 1-f_{td} \right)\times bid \times \left( 1-f_c \right) \times \left( 1-f_{tc} \right) -1
\\
roc_{case2}=\frac { c \times xy}{\left(y+c \right )^2} \times \left(1-f_{td} \right )
```
With:

- k: Capital in quote
- x: Quote reserve in pool
- y: Asset reserve in pool
- fc: Market order fees
- f_{tc}: Withdrawal fees (CEX to DEX)
- f_{td}: Withdrawal fees (DEX to CEX)
- fd: Swap fee on DEX

