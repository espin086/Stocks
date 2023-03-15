################################
#Manual import program

#Importing the data
my_dir <- "C:/Users/ESPIJ090.WDW/whalewisdom - data/"
setwd(my_dir)
stocks <- read.csv("stocks.csv", header = FALSE)

#Adding names since export didn't capture names, should fix this and delete this code later.

data_names <- c("stock_id","symbol","exchange", "name", "market_cap", "shares_outstanding", "institution_percentage", "price", "datetime", "range_low", "range_high", "fifty_two_week_low", "fifty_two_week_high","open","volume","average","dividend","yield","earnings_per_share","beta","price_to_earnings")

names(stocks) <- data_names

#Keep only stocks in the NYSE or Nasdaq.
stocks <- stocks[ which(stocks$exchange=='nasdaq'| stocks$exchange=='nyse'), ]

#Removing foreign stocks identified by the (adr) symbol.
stocks <-stocks[- grep("(adr)", stocks$name),]

#Quick data exploration

str(stocks)
summary(stocks)


################################
#Data Cleaning

#Adjusting stock percentage...don't use this data, keep as is.
stocks_no100plus <- subset(stocks, institution_percentage <= 100 )


#Should have only 1 stock symbol.
summary(stocks)

#I thought we said we would limit our analysis to nasdaq and nyse? Looks like the names are dirty as well.
table(stocks$exchange)

#Can stocks be in more than one exchange?
table(stocks$exchange,stocks$symbol)



#Can we set up a a different set of tables for dividends, yield, earnings_per_share, beta, and price-to-earnings.

################################
#Sum of Market Capitalization for Entire Stock Market

institution_share <- function(data) {
        total_value <- sum(data$market_cap)
        
        #Calculating Institutional Ownership of Stocks
        data$institution_percentage <- data$institution_percentage/100
        institution_value <- sum(data$institution_percentage*data$market_cap)
        
        #Institutional Control
        print("Total Value is...")
        print(total_value)
        
        print("Total Institutional Value is...")
        print(institution_value)
        
        print("This means that institutions could own")
        print(institution_value/total_value)
        print("of the market")
        
}

institution_share(stocks)
institution_share(stocks_no100plus)

#The following steps are to take the analysis to rattle to check for prediction accuracy.

#Spliting data into dividend and non-dividend companies
stocks_nodividend <- stocks[ which(stocks$dividend==0), ]
stocks_dividend <- stocks[ which(stocks$dividend>0), ]



write.csv(stocks, "stocks_clean.csv")
write.csv(stocks_dividend, "stocks_dividend.csv")
write.csv(stocks_nodividend, "stocks_nodividend.csv")

library(rattle)
rattle()




