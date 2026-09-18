-- ERCOT CRR Market Analytics -- SQL Server schema
--
-- Run this against the target database (the one named in SQL_SERVER_DATABASE
-- / your DATABASE_URL) to create the table the backend reads from.
-- If you already have CRR auction data in a differently-shaped table,
-- create a VIEW with this name and these exact column names/types instead
-- of moving your real table -- the backend only ever does a plain
-- `SELECT * FROM crr_auction_records`, so a view works identically.

IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_NAME = 'crr_auction_records'
)
BEGIN
    CREATE TABLE crr_auction_records (
        id               INT IDENTITY(1,1) PRIMARY KEY,
        auction_month    VARCHAR(7)    NOT NULL,  -- 'YYYY-MM', e.g. '2026-01'
        source           VARCHAR(50)   NOT NULL,  -- ERCOT settlement point code, e.g. 'HB_WEST'
        sink             VARCHAR(50)   NOT NULL,  -- ERCOT settlement point code, e.g. 'HB_HOUSTON'
        crr_type         VARCHAR(20)   NOT NULL,  -- 'OBLIGATION' or 'OPTION'
        time_of_use      VARCHAR(20)   NOT NULL,  -- 'PEAK_WD', 'PEAK_WE', or 'OFF_PEAK'
        clearing_price   FLOAT         NOT NULL,  -- $/MWh, can be negative
        awarded_mw       FLOAT         NOT NULL,  -- MW awarded in this auction line item
        participant      VARCHAR(200)  NOT NULL   -- CRR Account Holder / participant name
    );

    CREATE INDEX ix_crr_auction_records_pair
        ON crr_auction_records (source, sink);

    CREATE INDEX ix_crr_auction_records_month
        ON crr_auction_records (auction_month);
END
GO

-- Sanity-check query after loading real data -- the backend expects
-- crr_type to be exactly 'OBLIGATION' or 'OPTION' (uppercase) and
-- time_of_use to be exactly 'PEAK_WD', 'PEAK_WE', or 'OFF_PEAK'.
-- Run this after an initial data load to catch mismatches before pointing
-- the backend at this table:
--
-- SELECT DISTINCT crr_type FROM crr_auction_records;
-- SELECT DISTINCT time_of_use FROM crr_auction_records;
-- SELECT COUNT(*) AS row_count, MIN(auction_month) AS earliest, MAX(auction_month) AS latest
--   FROM crr_auction_records;
