from decimal import Decimal

if __name__ == '__main__':
    coeff = int(1e8)

    assetDepth = Decimal('4628680932816'); print('assetDepth', assetDepth / coeff)
    runeDepth = Decimal('125309720026613'); print('runeDepth', runeDepth / coeff)

    # dex_price_in_rune = Decimal('27.85'); print('dex_price_in_rune', dex_price_in_rune)
    dex_price_in_rune = Decimal('26.85'); print('dex_price_in_rune', dex_price_in_rune)

    X = runeDepth
    Y = assetDepth

    asset_price = X / Y; print('asset_price', asset_price)
    market_delta = (asset_price - dex_price_in_rune) / asset_price; print('market_delta', market_delta)

    trade_size = (market_delta * runeDepth * assetDepth) / (5 * assetDepth); print('trade_size', trade_size / coeff)

    output = (trade_size * runeDepth * assetDepth) / pow(trade_size + assetDepth, 2); print('output', output / coeff)

    new_assetDepth = assetDepth + trade_size
    new_runeDepth = runeDepth + output

    new_pool_price = new_runeDepth / new_assetDepth; print('new_pool_price', new_pool_price)