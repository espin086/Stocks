-- schema version 1 with sample rows; produced by scripts/schema_fixture.py
BEGIN TRANSACTION;
CREATE TABLE fetch_log (
	id TEXT NOT NULL, 
	provider TEXT NOT NULL, 
	dataset TEXT NOT NULL, 
	symbol TEXT NOT NULL, 
	range_start DATE NOT NULL, 
	range_end DATE NOT NULL, 
	fetched_at TEXT NOT NULL, 
	ttl_seconds INTEGER NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "fetch_log" VALUES('8ef11d10a12d4fe1a75fc10dd529d785','yfinance','prices_adj_close','AAPL','2020-01-01','2020-01-31','2026-09-12T10:00:00.000000Z',86400);
CREATE TABLE kv (
	"key" TEXT NOT NULL, 
	value TEXT, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY ("key")
);
INSERT INTO "kv" VALUES('greeting','{"hello":"world"}','2026-09-12T18:17:17.108386Z');
CREATE TABLE observation (
	provider TEXT NOT NULL, 
	dataset TEXT NOT NULL, 
	symbol TEXT NOT NULL, 
	date DATE NOT NULL, 
	value FLOAT, 
	CONSTRAINT pk_observation PRIMARY KEY (provider, dataset, symbol, date)
);
INSERT INTO "observation" VALUES('yfinance','prices_adj_close','AAPL','2020-01-02',100.5);
INSERT INTO "observation" VALUES('yfinance','prices_adj_close','AAPL','2020-01-03',101.0);
CREATE TABLE schema_version (
	version INTEGER NOT NULL, 
	name TEXT NOT NULL, 
	applied_at TEXT NOT NULL, 
	PRIMARY KEY (version)
);
INSERT INTO "schema_version" VALUES(1,'initial-cache-and-kv','2026-09-12T00:00:00.000000Z');
CREATE TABLE series_meta (
	provider TEXT NOT NULL, 
	dataset TEXT NOT NULL, 
	symbol TEXT NOT NULL, 
	meta TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	CONSTRAINT pk_series_meta PRIMARY KEY (provider, dataset, symbol)
);
INSERT INTO "series_meta" VALUES('yfinance','prices_adj_close','AAPL','{"currency":"USD"}','2026-09-12T18:17:17.106723Z');
COMMIT;
