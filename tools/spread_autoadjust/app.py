import os
import sys
from datetime import timedelta, datetime
from pprint import pprint

import streamlit as st
import numpy as np
import yaml

sys.path.append(os.path.abspath('../..'))
from tools.spread_autoadjust.lib.worker import Worker

def load_style(st, filename):
    with open(filename, 'r') as fp:
        st.markdown(f'<style>{fp.read()}</style>', unsafe_allow_html=True)

if __name__ == '__main__':
    with open('config.yaml', 'r') as fp:
        config = yaml.load(fp, Loader=yaml.Loader)

    load_style(st, 'lib/style.css')

    config['start_date'] = datetime.combine(st.sidebar.date_input('Start Date'), datetime.min.time())
    # config['end_date'] = st.sidebar.date_input('End Date')
    config['end_date'] = config['start_date'] + timedelta(hours=3)

    config['target_spread'] = st.sidebar.slider('Target Spread (bps)', value=50, min_value=20, max_value=100, step=1) * 1e-4

    config['placeholder'] = st.empty()

    worker = Worker(config)

    if st.sidebar.button('Start'):
        worker.run()