#Importing data from Google Sheets

library(RCurl)
library(foreign)

url <- "https://docs.google.com/spreadsheets/d/1UT-9U2mNLNY5YwqqO-2tVVQAKPfmd2YpXamNDMlUvV8/pub?output=csv"
investments <- getURL(url)                
investments <- read.csv(textConnection(investments), header = TRUE, skip =0)

###########################
#Goals

#Any uninvested money goes into a savings account with no risk earning 3%

#1. Maximize the average return per dollar
#2. Have an average risk of no more than 5 
        #(averaged over the 5 investments not the savings account)
#3. Invest at least 20% in commercial loans
#4. The amount of second mortgages and personal loans combined should be no 
        #higher than the amount of first mortgages


#######################
#Objective Function
returns <- c(investments[,2])/100

#######################
#Constraints

#Budget constraint of $100 Million
rhs.budget <- c(1)
lhs.budget <- c(1, 1, 1, 1, 1, 1)

#Average Risk no more than 5
risk <- c(investments[,3])
rhs.risk <- c(5)
lhs.risk <- risk - rep(rhs.risk,length(risk))
rhs.risk <- c(0)

#Invest at least 20% in commercial loans
minimum.investment <- c(.20)
rhs.c.loan <- c(0)
lhs.c.loan <- rep(1, length(risk))*minimum.investment - c(0, 0, 0, 1, 0, 0)

#second mortgages and personal loans combined should be no higher than first mortgages
lhs.mortgages <- c(-1, 2, 3, 0, 0, 0)
rhs.mortgages <- c(0)


#########
#Aggregating Constraints
lhs.constraint <- rbind(lhs.budget, lhs.risk, lhs.c.loan, lhs.mortgages)
rhs.constraint <- rbind(rhs.budget, rhs.risk, rhs.c.loan, rhs.mortgages)

#########
#Solving Optimization proglem
library(linprog)
answer <- solveLP(returns, rhs.constraint, lhs.constraint, maximum = TRUE,
                  const.dir = c("==", "<=", "<=", "<="), lpSolve = TRUE)

answer
