"""
This module provides a class for retrieving stock market data from Yahoo Finance.

Usage:
    Create a StockMarketData object with the desired stock symbol.
    Call the get_data() method with the desired start and end dates to retrieve the stock data.
    Call the get_open_price(), get_close_price(), get_high_price(), and get_low_price() methods to access the data.

Example:
    data = StockMarketData('AAPL')
    data.get_data('2022-01-01', '2022-02-01')
    print(data.get_open_price())

"""

import argparse
import yfinance as yf

class StockMarketData:
    def __init__(self, symbol):
        self.symbol = symbol
        self.data = None

    def get_data(self, start_date, end_date):
        self.data = yf.download(self.symbol, start=start_date, end=end_date)

    def get_open_price(self):
        return self.data['Open']

    def get_close_price(self):
        return self.data['Close']

    def get_high_price(self):
        return self.data['High']

    def get_low_price(self):
        return self.data['Low']



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Retrieve stock market data from Yahoo Finance.')
    parser.add_argument('symbol', help='the stock symbol to retrieve data for')
    parser.add_argument('start_date', help='the start date for the data (YYYY-MM-DD)')
    parser.add_argument('end_date', help='the end date for the data (YYYY-MM-DD)')
    args = parser.parse_args()

    data = StockMarketData(args.symbol)
    data.get_data(args.start_date, args.end_date)
    print(data.get_open_price())
    print(data.get_close_price())
    print(data.get_high_price())
    print(data.get_low_price())





    print(type(data.get_low_price()))
