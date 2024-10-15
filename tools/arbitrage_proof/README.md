# Thorchain arbitrage


### Run with: 
`python app.py --add yaml/arbitrage.yaml --add secrets.yaml`

### Run continuously with:
`python app_continue.py --add yaml/arbitrage.yaml --add secrets.yaml`

### Secrets.yaml

Include login and information about DEX wallet, CEX and influx database.

```yaml
influx:
  host: ****
  username: ****
  password: ****
  database: ****

cex:
  key: ****
  secret: ****
  address: ****
  memo: ****

dex:
  address: ****
  private_key: ****
```

### Documentation
https://app.gitbook.com/@aries-3/s/aries-1/thorswap-bot/flow-of-the-strategy
