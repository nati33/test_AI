-- ============================================================
-- Gov IL Ownership Transitions with Pango Account Matching
-- Sources:
--   gov : externals.gov_history_ownership_car_changes
--         columns: _id, mispar_rechev, baalut_dt (YYYYMM), baalut
--   cars: natis.cars_movements_step_1
--         columns: user_phone_number, account_gk, car_no,
--                  transaction, first_use, last_use, ...
--
-- Goal: One row per ownership transition per car.
--       • from_account / to_account = Pango account with most
--         transactions during each ownership period.
--       • number_of_unique_phones = distinct phones in the TO period.
--       • First ownership row is excluded (no "from" exists).
--       • Current/active ownership IS included with to_date = NULL.
-- ============================================================

WITH

-- ----------------------------------------------------------------
-- STEP 1: Gov ownership periods.
--         LEAD() gives each period's end date (= start of the
--         next one); NULL means the period is still active.
-- ----------------------------------------------------------------
gov_periods AS (
    SELECT
        mispar_rechev                                              AS car_no,
        baalut                                                     AS ownership_type,
        TO_DATE(baalut_dt || '01', 'YYYYMMDD')                    AS period_start,

        LEAD(TO_DATE(baalut_dt || '01', 'YYYYMMDD')) OVER (
            PARTITION BY mispar_rechev
            ORDER BY baalut_dt
        )                                                          AS period_end,   -- NULL = active

        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt ASC
        )                                                          AS seq_asc,      -- 1 = first ever
        ROW_NUMBER() OVER (
            PARTITION BY mispar_rechev ORDER BY baalut_dt DESC
        )                                                          AS seq_desc      -- 1 = current

    FROM externals.gov_history_ownership_car_changes
),

-- ----------------------------------------------------------------
-- STEP 2: For each gov period, find the main Pango account
--         (highest total transactions) and distinct phone count.
--         A Pango row belongs to a period when its first_use
--         falls within [period_start, period_end).
-- ----------------------------------------------------------------
pango_period_agg AS (
    SELECT
        g.car_no,
        g.period_start,
        p.account_gk,
        SUM(p.transaction)                                         AS total_transactions,
        COUNT(DISTINCT p.user_phone_number)                        AS unique_phones,

        ROW_NUMBER() OVER (
            PARTITION BY g.car_no, g.period_start
            ORDER BY SUM(p.transaction) DESC
        )                                                          AS rn

    FROM gov_periods                          g
    LEFT JOIN natis.cars_movements_step_1     p
        ON  g.car_no                    = p.car_no
        AND CAST(p.first_use AS DATE)  >= g.period_start
        AND (CAST(p.first_use AS DATE)  < g.period_end
             OR g.period_end            IS NULL)

    GROUP BY g.car_no, g.period_start, p.account_gk
),

main_account_per_period AS (
    SELECT
        car_no,
        period_start,
        account_gk                                                 AS main_account,
        unique_phones
    FROM pango_period_agg
    WHERE rn = 1
),

-- ----------------------------------------------------------------
-- STEP 3: Build transition rows with LAG.
--         Each row = one ownership period, enriched with the
--         previous period's details via LAG().
-- ----------------------------------------------------------------
gov_transitions AS (
    SELECT
        car_no,

        -- FROM period (previous ownership)
        LAG(ownership_type) OVER (
            PARTITION BY car_no ORDER BY period_start
        )                                                          AS from_ownership_type,
        LAG(period_start) OVER (
            PARTITION BY car_no ORDER BY period_start
        )                                                          AS from_date,

        -- Date the car changed hands
        period_start                                               AS change_date,

        -- TO period (this ownership)
        ownership_type                                             AS to_ownership_type,
        period_end                                                 AS to_date,      -- NULL = still active

        seq_asc,
        seq_desc

    FROM gov_periods
)

-- ================================================================
-- FINAL OUTPUT
-- ================================================================
SELECT
    t.car_no,

    -- FROM period ---------------------------------------------------
    fa.main_account                                                AS from_account,
    t.from_ownership_type,
    t.from_date,

    -- Transition date -----------------------------------------------
    t.change_date,

    -- TO period -----------------------------------------------------
    ta.main_account                                                AS to_account,
    t.to_ownership_type,
    t.to_date,                        -- NULL = this ownership is still active
    ta.unique_phones                                               AS number_of_unique_phones

FROM gov_transitions t

-- Main account during the FROM period
LEFT JOIN main_account_per_period fa
    ON  t.car_no    = fa.car_no
    AND t.from_date = fa.period_start

-- Main account during the TO period
LEFT JOIN main_account_per_period ta
    ON  t.car_no      = ta.car_no
    AND t.change_date = ta.period_start

-- Exclude the very first ownership row UNLESS it is also the
-- current one (car has had only one owner ever → keep it)
WHERE t.seq_asc > 1
   OR t.seq_desc = 1

ORDER BY
    t.car_no,
    t.change_date
;
