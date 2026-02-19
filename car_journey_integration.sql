-- ============================================================
-- Car Summary: One Row per Car (Gov IL as base)
-- Sources:
--   1. gov_il_cars   : government ownership registry
--      columns: _id, mispar_rechev, baalut_dt (YYYYMM), baalut
--   2. pango_cars    : user-car usage from Pango
--      columns: user_phone_number, account_gk, car_no, ...
--
-- Goal: One row per car (from gov registry).
--       Each row shows the latest Pango account, total phone
--       count, and the car's first/last official ownership.
-- ============================================================

WITH

-- ----------------------------------------------------------------
-- STEP 1: Rank gov rows per car to extract first and last
--         ownership period (baalut_dt is YYYYMM).
-- ----------------------------------------------------------------
gov_ranked AS (
    SELECT
        mispar_rechev                                              AS car_no,
        baalut                                                     AS ownership_type,
        TO_DATE(baalut_dt || '01', 'YYYYMMDD')                    AS ownership_date,

        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt ASC
        )                                                          AS seq_asc,   -- 1 = earliest
        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt DESC
        )                                                          AS seq_desc   -- 1 = latest

    FROM gov_il_cars               -- <<< replace with your actual table/schema
),

-- ----------------------------------------------------------------
-- STEP 2: Collapse gov to one row per car.
-- ----------------------------------------------------------------
gov_summary AS (
    SELECT
        car_no,
        MAX(CASE WHEN seq_asc  = 1 THEN ownership_date   END)     AS first_ownership_date,
        MAX(CASE WHEN seq_asc  = 1 THEN ownership_type   END)     AS first_owner_type,
        MAX(CASE WHEN seq_desc = 1 THEN ownership_date   END)     AS last_ownership_date,
        MAX(CASE WHEN seq_desc = 1 THEN ownership_type   END)     AS last_owner_type
    FROM gov_ranked
    GROUP BY car_no
),

-- ----------------------------------------------------------------
-- STEP 3: Rank Pango rows per car by last_use to find the most
--         recent account_gk (the "current" holder).
-- ----------------------------------------------------------------
pango_ranked AS (
    SELECT
        car_no,
        account_gk,
        user_phone_number,
        CAST(last_use AS TIMESTAMP)                                AS last_use_ts,
        ROW_NUMBER() OVER (
            PARTITION BY car_no
            ORDER BY CAST(last_use AS TIMESTAMP) DESC
        )                                                          AS rn
    FROM pango_cars                -- <<< replace with your actual table/schema
),

-- ----------------------------------------------------------------
-- STEP 4: Collapse Pango to one row per car.
--         - latest_account_gk : account that most recently used the car
--         - num_phones         : total distinct phones ever linked to the car
-- ----------------------------------------------------------------
pango_summary AS (
    SELECT
        car_no,
        MAX(CASE WHEN rn = 1 THEN account_gk END)                 AS latest_account_gk,
        COUNT(DISTINCT user_phone_number)                          AS num_phones
    FROM pango_ranked
    GROUP BY car_no
)

-- ================================================================
-- FINAL OUTPUT: One row per car
-- ================================================================
SELECT
    g.car_no,
    p.latest_account_gk                                           AS account_gk,
    p.num_phones                                                   AS number_of_phones,
    g.first_ownership_date,
    g.last_ownership_date,
    g.first_owner_type,
    g.last_owner_type

FROM gov_summary     g
LEFT JOIN pango_summary p
    ON g.car_no = p.car_no

ORDER BY g.car_no
;
