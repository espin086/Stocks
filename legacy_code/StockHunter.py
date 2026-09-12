from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler

from StockMarketData import StockMarketData


today = datetime.today().strftime('%Y-%m-%d')
start = (datetime.today() - timedelta(days=5*365)).strftime('%Y-%m-%d')



data = StockMarketData('AAPL')
data.get_data(start, today)
print(data.get_close_price())
