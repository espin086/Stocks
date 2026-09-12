#Money available equals 401k saving plus historical savings rate for home
#401k equals Julie's 400 per month & JJ 4.5% of 135k plus
#These savings are adjusted upwared a modest by 3% per year
#to account for wage inflation

#Similarly 401k contributions are assumed to increase by 3% per year 
#The return on 401k is assumed at the historical average of 10% yearly

#While contributing the contributions save 30% in taxes
#After 30 years contributions stop and disbursements begin taxed at 30%

#Student loans assume pay 12k extra per year, govt loan paid off after 3 years
#Remaining private loan paid off after 3 years
#Assuming all loans are at 30 percent interest

#WARNING: As of end of February, not all assumptions have been validated
#WARNING: Consult with Wealth Advisor for net present value calcs

setwd("~/Desktop")
cf <- read.csv("npv.data.csv")

#Converting CF to NPV
library(FinCal)

###################################################################
#Setting up Linear Programming Problem

#######################
#Objective Function

#discount rate
rate <- 0.05

npvs <- c(npv(rate, cf$Extra.Student.net), 
          npv(rate, cf$Retirement.401k.net), 
          npv(rate, cf$Home.pay.off.net), 
          npv(rate, cf$Home.purchase.return), 
          npv(rate, cf$invest.stocks.net), 
          npv(rate, cf$save.money.ret))

#######################
#Constraints

#Money availability for each time period
rhs.constraints <- cf$financial.constraints
rhs.constraints <- as.matrix(rhs.constraints)
#Money required to invest
lhs.constraints <- cbind(cf$Extra.Student.Payments * -1, 
                         cf$Retirement.401k.payments * -1,
                         cf$Home.pay.off.payment *-1,
                         cf$Home.purchase.payment * -1,
                         cf$invest.stocks.payment*-1,
                         cf$save.money.bank*-1)
lhs.constraints <- as.matrix(lhs.constraints)
#######################
#Solving the Linear Programming Problem
library(linprog)
answer <- solveLP(npvs, rhs.constraints, lhs.constraints, maximum = TRUE)

answer$opt
answer$solution
answer$con














