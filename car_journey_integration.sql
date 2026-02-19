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
--       • All gov rows appear (1 gov row = 1 output row).
--       • First row: from_account / from_ownership_type / from_date = NULL.
--       • Current/active ownership: to_date = NULL.
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
        )                                                          AS period_end    -- NULL = active

    FROM externals.gov_history_ownership_car_changes
),

-- ----------------------------------------------------------------
-- STEP 2a: Pre-aggregate pango BEFORE the range join.
--          Collapse to one row per (car, account, phone) and cast
--          first_use to DATE once here — avoids repeating CAST on
--          millions of rows inside the join condition.
--          This drastically reduces the size of the range join.
-- ----------------------------------------------------------------
pango_agg AS (
    SELECT
        car_no,
        account_gk,
        user_phone_number,
        CAST(MIN(first_use) AS DATE)                               AS first_use_date,
        SUM(transaction)                                           AS total_transactions
    FROM natis.cars_movements_step_1
    GROUP BY car_no, account_gk, user_phone_number
),

-- ----------------------------------------------------------------
-- STEP 2b: Range-join the pre-aggregated pango to gov periods.
--          Because pango_agg is already collapsed, this join is
--          far cheaper than joining the raw table.
--          Pick the main account (most transactions) per period.
-- ----------------------------------------------------------------
pango_per_period AS (
    SELECT
        g.car_no,
        g.period_start,
        p.account_gk,
        SUM(p.total_transactions)                                  AS total_transactions,
        COUNT(DISTINCT p.user_phone_number)                        AS unique_phones,

        ROW_NUMBER() OVER (
            PARTITION BY g.car_no, g.period_start
            ORDER BY SUM(p.total_transactions) DESC
        )                                                          AS rn

    FROM gov_periods                          g
    LEFT JOIN pango_agg                       p
        ON  g.car_no           = p.car_no
        AND p.first_use_date  >= g.period_start
        AND (p.first_use_date  < g.period_end
             OR g.period_end   IS NULL)

    GROUP BY g.car_no, g.period_start, p.account_gk
),

main_account_per_period AS (
    SELECT
        car_no,
        period_start,
        account_gk                                                 AS main_account,
        unique_phones
    FROM pango_per_period
    WHERE rn = 1
),

-- ----------------------------------------------------------------
-- STEP 3: Build transition rows with LAG.
-- ----------------------------------------------------------------
gov_transitions AS (
    SELECT
        car_no,

        LAG(ownership_type) OVER (
            PARTITION BY car_no ORDER BY period_start
        )                                                          AS from_ownership_type,
        LAG(period_start) OVER (
            PARTITION BY car_no ORDER BY period_start
        )                                                          AS from_date,

        period_start                                               AS change_date,
        ownership_type                                             AS to_ownership_type,
        period_end                                                 AS to_date       -- NULL = still active

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

LEFT JOIN main_account_per_period fa
    ON  t.car_no    = fa.car_no
    AND t.from_date = fa.period_start

LEFT JOIN main_account_per_period ta
    ON  t.car_no      = ta.car_no
    AND t.change_date = ta.period_start

ORDER BY
    t.car_no,
    t.change_date
;
