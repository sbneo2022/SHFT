import math
import os
import sys
from datetime import timedelta

import pandas as pd
import streamlit as st
import tqdm
import stqdm

sys.path.append(os.path.abspath('../../..'))
from tools.spread_autoadjust.fn.moving_max import MovingMax
from tools.spread_autoadjust.lib.db import Db


BLOCK_LENGTH = 5

class Worker:
    def __init__(self, config: dict):
        self._config = config

        self._db = Db(config)

        self._placeholder = self._config['placeholder']


    def run(self):
        print('loading data')

        block = timedelta(minutes=BLOCK_LENGTH)

        length = self._config['end_date'] - self._config['start_date']

        n_of_blocks = math.ceil(length / block)

        print(block, length, n_of_blocks)

        # fn = Fixed(self._config)
        fn = MovingMax(self._config)
        result = pd.DataFrame()
        flip_counter = 0

        loop = stqdm.stqdm(range(n_of_blocks), desc=f'Processing data by {BLOCK_LENGTH} min blocks')

        for block_idx in loop:
            _start_date = self._config['start_date'] + block_idx * block
            _end_date = _start_date + block

            loop.set_description(desc=f'{_start_date}-{_end_date}')
            source_data = self._db.getPoints(
                startDate=_start_date,
                endDate=_end_date,
                tags={'symbol': 'DOTUSDT', 'exchange': 'BINANCE.FUTURES'},
                fields=['spread_arbitrage'],
            )

            for idx, data in source_data.iterrows():
                spread = data['spread_arbitrage']
                event = fn.getEvent(spread, time=idx)

                result.loc[idx, 'spread'] = spread * 10000
                result.loc[idx, 'high'] = event.high * 10000
                result.loc[idx, 'low'] = event.low * 10000

                flip_counter = flip_counter + 1 if event.flip else flip_counter


        print(result)

        st.line_chart(result)
        st.write(flip_counter)
        # self._placeholder.text("Hello")
        # st.write(source_data)