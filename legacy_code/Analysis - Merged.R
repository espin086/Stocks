library(doParallel)
cl <- makeCluster(4)
registerDoParallel(cl)

setwd("C:/Users/ESPIJ090.WDW/whalewisdom - data/")

#Modeling 1 stock at a time
training[ticker=="DIS",]
testing[ticker=="DIS",]
validation[ticker=="DIS",]


training <- read.csv("training.csv")
testing <- read.csv("testing.csv")
validation <-read.csv("validation.csv")

training <- training[c(-1)]
testing <- testing[c(-1)]
validation <- validation[c(-1)]



#######################################################################
#Training the Models
library(caret)

#Random Forests.
fit.rf <- train(returns ~.,method="rf",preProcess=c("pca"),data=training) 
pred.rf <- predict(fit.rf,testing)
confusionMatrix(testing$returns, pred.rf)

#KNN
fit.knn <- train(returns ~.,method="knn",preProcess=c("pca"),data=training) 
pred.knn <- predict(fit.knn,testing)
confusionMatrix(testing$returns, pred.knn)

#Neural Networks.
fit.nnet <- train(returns ~.,method="nnet", preProcess=c("pca"),data=training) 
pred.nnet <- predict(fit.nnet,testing)
confusionMatrix(testing$returns, pred.nnet)


#general boosting model.
fit.gbm <- train(returns ~.,method="gbm",preProcess=c("pca"),data=training) 
pred.gbm <- predict(fit.gbm,testing)
confusionMatrix(testing$returns, pred.gbm)

########################################
# Ensemble Model 04-28-2015

#ensemble model to take advantages of the strengths and weaknesses of each model.
predDF <- data.frame(pred.rf ,pred.knn, pred.nnet, pred.gbm,returns=testing$returns)
combModFit <- train(returns ~.,method="lm",data=predDF)

#Prediction on validation set for final assessment.
pred.rf.v <- predict(fit.rf,validation)
pred.knn.v <- predict(fit.knn,validation)
pred.nnet.v <- predict(fit.nnet,validation)
pred.gbm.v <- predict(fit.gbm,validation)

predVDF <- data.frame(pred.rf=pred.rf.v, pred.knn=pred.knn.v, pred.nnet=pred.nnet.v, pred.gbm=pred.gbm.v)
combPredV <- predict(combModFit,predVDF)


confusionMatrix(validation$returns, pred.rf.v)
confusionMatrix(validation$returns, pred.knn.v)
confusionMatrix(validation$returns, pred.nnet.v)
confusionMatrix(validation$returns, pred.gbm.v)
confusionMatrix(validation$returns, combPredV)
