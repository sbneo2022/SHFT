import os; import sys
from datetime import datetime
from pathlib import Path

import math
import pandas as pd

sys.path.append(os.path.abspath('../..'))
from tools.mm.lib import load_products, Binance, KEY

if __name__ == '__main__':

    print('Parsing products...')

    products = load_products('products.txt')

    print('Loading market data...')

    binance = Binance()
    for product, info in products.items():
        sys.stdout.write(f'{product} '); sys.stdout.flush()
        tick = binance.getTick(product)
        ask, bid = binance.getBidAsk(product)

        midpoint = 0.5 * (ask + bid)

        info[KEY.MAX_ALLOCATION] = round(info[KEY.OUTER_QTY] * midpoint, 2)


        inner = midpoint * (1 + 0.5 * info[KEY.INNER_VALUE])
        min_distance = bid * (1 - 0.001)

        info[KEY.DISTANCE] = math.floor((inner - midpoint) / tick)
        info[KEY.MIN_DISTANCE] = math.floor((bid - min_distance) / tick)

    df = pd.DataFrame().from_dict(products, orient='index')

    filename = datetime.now().strftime('products_report.%d.%m.%Y.csv')

    filename = Path(__file__).parent / Path(filename)

    df.to_csv(filename)

    print()
    print('-' * 80)
    print(f'Saved to {filename.resolve()}')



