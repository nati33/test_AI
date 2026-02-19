-- ============================================================
-- Car Journey Across Users
-- Sources:
--   1. gov_il_cars   : government ownership registry
--      columns: _id, mispar_rechev, baalut_dt (YYYYMM), baalut
--   2. pango_cars    : user-car usage from Pango
--      columns: user_phone_number, account_gk, car_no, make_desc,
--               up_on_road_date, ownership, gas_type, license_exe,
--               transaction, first_use, last_use, car_segment_group,
--               car_tenure_pango, first_owner_date, rank_1,
--               last_owner_date, car_ownership_tenure, car_tenure,
--               usage_tenure, car_active_ind
--
-- Goal: For each car, show every transition between users.
--       Each row = one user holding the car.
--       change_date = when the car moved to this user (NULL for
--       the very first user in the timeline).
--       first_owner / last_owner = first and last official owner
--       from the government registry.
-- ============================================================

WITH

-- ----------------------------------------------------------------
-- STEP 1: Consolidate Pango to one row per (car, account).
--         The same account_gk may appear with multiple phone
--         numbers for the same car — we collapse those here.
-- ----------------------------------------------------------------
pango_per_account AS (
    SELECT
        car_no,
        account_gk,
        -- Representative phone (earliest alphabetically / numerically)
        MIN(user_phone_number)                        AS representative_phone,

        -- Car metadata (consistent within a car)
        MIN(make_desc)                                AS make_desc,
        MIN(up_on_road_date)                          AS up_on_road_date,
        MIN(gas_type)                                 AS gas_type,
        MIN(license_exe)                              AS license_exe,

        -- Earliest first_use across all phone rows for this account+car
        MIN(CAST(first_use AS TIMESTAMP))             AS first_use,
        -- Latest last_use across all phone rows for this account+car
        MAX(CAST(last_use  AS TIMESTAMP))             AS last_use,

        -- Active flag: 1 if any row for this account+car is active
        MAX(car_active_ind)                           AS car_active_ind,

        -- Aggregate tenure
        SUM(car_tenure_pango)                         AS total_tenure_days,
        SUM(transaction)                              AS total_transactions,

        -- Ownership period stored in Pango
        MIN(first_owner_date)                         AS pango_first_owner_date,
        MAX(last_owner_date)                          AS pango_last_owner_date,
        MAX(car_ownership_tenure)                     AS car_ownership_tenure,
        MAX(car_tenure)                               AS car_tenure

    FROM pango_cars                  -- <<< replace with your actual table/schema
    GROUP BY car_no, account_gk
),

-- ----------------------------------------------------------------
-- STEP 2: Build the ordered timeline of users per car.
--         LAG() gives us the previous account (= "old" user).
--         ROW_NUMBER() gives the position in the car's history.
-- ----------------------------------------------------------------
pango_journey AS (
    SELECT
        car_no,
        account_gk,
        representative_phone,
        make_desc,
        up_on_road_date,
        gas_type,
        license_exe,
        first_use,
        last_use,
        car_active_ind,
        total_tenure_days,
        total_transactions,
        pango_first_owner_date,
        pango_last_owner_date,
        car_ownership_tenure,
        car_tenure,

        -- Position of this user in the car's journey (1 = first ever user)
        ROW_NUMBER() OVER (
            PARTITION BY car_no
            ORDER BY first_use
        )                                             AS user_seq,

        -- Previous user's account_gk  (NULL for the first user)
        LAG(account_gk) OVER (
            PARTITION BY car_no
            ORDER BY first_use
        )                                             AS prev_account_gk,

        -- Previous user's phone
        LAG(representative_phone) OVER (
            PARTITION BY car_no
            ORDER BY first_use
        )                                             AS prev_user_phone,

        -- When the previous user last had the car
        LAG(last_use) OVER (
            PARTITION BY car_no
            ORDER BY first_use
        )                                             AS prev_user_last_use

    FROM pango_per_account
),

-- ----------------------------------------------------------------
-- STEP 3: Build the Government ownership timeline.
--         baalut_dt is YYYYMM; we convert it to the 1st of
--         that month for date arithmetic.
-- ----------------------------------------------------------------
gov_ownership_timeline AS (
    SELECT
        mispar_rechev                                             AS car_no,
        baalut_dt,
        baalut                                                    AS ownership_type,
        TO_DATE(baalut_dt || '01', 'YYYYMMDD')                   AS ownership_start_date,
        -- End of this ownership period = start of the next one (NULL = current)
        LEAD(TO_DATE(baalut_dt || '01', 'YYYYMMDD')) OVER (
            PARTITION BY mispar_rechev
            ORDER BY baalut_dt
        )                                                         AS ownership_end_date,

        -- Rank for first/last extraction
        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt ASC
        )                                                         AS seq_asc,
        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt DESC
        )                                                         AS seq_desc

    FROM gov_il_cars                 -- <<< replace with your actual table/schema
),

-- ----------------------------------------------------------------
-- STEP 4: Extract first-ever and latest owner from Gov IL per car.
-- ----------------------------------------------------------------
gov_first_last AS (
    SELECT
        car_no,

        -- First official owner (earliest baalut_dt)
        MAX(CASE WHEN seq_asc  = 1 THEN ownership_start_date END) AS gov_first_owner_date,
        MAX(CASE WHEN seq_asc  = 1 THEN ownership_type       END) AS gov_first_owner_type,

        -- Last/current official owner (latest baalut_dt)
        MAX(CASE WHEN seq_desc = 1 THEN ownership_start_date END) AS gov_last_owner_date,
        MAX(CASE WHEN seq_desc = 1 THEN ownership_type       END) AS gov_last_owner_type

    FROM gov_ownership_timeline
    GROUP BY car_no
),

-- ----------------------------------------------------------------
-- STEP 5 (optional enrichment): For each Pango user period, find
--         the Gov IL ownership type that was active at the time.
--         Useful to correlate "who officially owned it while this
--         user was driving it."
-- ----------------------------------------------------------------
pango_with_gov_at_time AS (
    SELECT
        j.car_no,
        j.account_gk,
        j.first_use,
        g.ownership_type                                          AS gov_ownership_at_use_time
    FROM pango_journey           j
    LEFT JOIN gov_ownership_timeline g
        ON  j.car_no      = g.car_no
        AND j.first_use  >= g.ownership_start_date
        AND (j.first_use  < g.ownership_end_date
             OR g.ownership_end_date IS NULL)     -- still current
)

-- ================================================================
-- FINAL OUTPUT: Car journey with transitions
-- ================================================================
SELECT
    -- --- Car identity ---
    j.car_no,
    j.make_desc,
    j.up_on_road_date,
    j.gas_type,
    j.license_exe,

    -- --- Journey position ---
    j.user_seq                                                    AS user_sequence_in_car_history,

    -- --- Previous holder ("old" user) ---
    j.prev_account_gk                                             AS old_account_gk,
    j.prev_user_phone                                             AS old_user_phone,
    j.prev_user_last_use                                          AS old_user_last_use_date,

    -- --- Current holder ("new" user) ---
    j.account_gk                                                  AS new_account_gk,
    j.representative_phone                                        AS new_user_phone,
    j.first_use                                                   AS new_user_first_use_date,

    -- End date: NULL when this user still has the car (active)
    CASE
        WHEN j.car_active_ind = 1 THEN NULL
        ELSE j.last_use
    END                                                           AS new_user_last_use_date,

    j.car_active_ind                                              AS is_currently_active,
    j.total_transactions,
    j.total_tenure_days,

    -- --- Change date ---
    -- NULL  → first user, no transfer happened before
    -- value → the date this user first took the car (= transfer event)
    CASE
        WHEN j.prev_account_gk IS NULL THEN NULL
        ELSE j.first_use
    END                                                           AS change_date,

    -- --- Gov IL: official first owner for this car ---
    g.gov_first_owner_date,
    g.gov_first_owner_type,

    -- --- Gov IL: official last (current) owner for this car ---
    g.gov_last_owner_date,
    g.gov_last_owner_type,

    -- --- Gov IL ownership type while this user had the car ---
    t.gov_ownership_at_use_time,

    -- --- Pango-derived ownership window ---
    j.pango_first_owner_date,
    j.pango_last_owner_date,
    j.car_ownership_tenure,
    j.car_tenure

FROM pango_journey                    j

-- First / last owner from Gov IL
LEFT JOIN gov_first_last              g
    ON  j.car_no = g.car_no

-- Gov ownership type active during this user's usage period
LEFT JOIN pango_with_gov_at_time      t
    ON  j.car_no      = t.car_no
    AND j.account_gk  = t.account_gk
    AND j.first_use   = t.first_use

ORDER BY
    j.car_no,
    j.first_use
;
