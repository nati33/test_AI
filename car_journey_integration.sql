-- ============================================================
-- Gov IL Ownership Transitions — one row per ownership change
-- Sources:
--   gov : externals.gov_history_ownership_car_changes
--         columns: _id, mispar_rechev, baalut_dt (YYYYMM), baalut
--   cars: natis.cars_movements_step_1  (available for future joins)
--
-- Goal: For each car, produce one row per ownership period.
--       Each row shows:
--         • from_ownership_type  – who owned it before  (NULL = first ever)
--         • to_ownership_type    – who owns it now
--         • from_date            – when the previous ownership started (NULL = first)
--         • to_date              – when THIS ownership started
-- ============================================================

WITH

-- ----------------------------------------------------------------
-- STEP 1: Convert baalut_dt (YYYYMM) to a real date and use
--         LAG() to pull in the previous ownership details.
-- ----------------------------------------------------------------
gov_transitions AS (
    SELECT
        mispar_rechev                                              AS car_no,

        -- Previous ownership type  (NULL for the very first row)
        LAG(baalut) OVER (
            PARTITION BY mispar_rechev
            ORDER BY baalut_dt
        )                                                          AS from_ownership_type,

        -- Current ownership type
        baalut                                                     AS to_ownership_type,

        -- Date the previous ownership started (NULL for the first row)
        LAG(TO_DATE(baalut_dt || '01', 'YYYYMMDD')) OVER (
            PARTITION BY mispar_rechev
            ORDER BY baalut_dt
        )                                                          AS from_date,

        -- Date THIS ownership started
        TO_DATE(baalut_dt || '01', 'YYYYMMDD')                    AS to_date

    FROM externals.gov_history_ownership_car_changes
)

-- ================================================================
-- FINAL OUTPUT: One transition row per ownership period per car
-- ================================================================
SELECT
    car_no,
    from_ownership_type,
    to_ownership_type,
    from_date,
    to_date

FROM gov_transitions

ORDER BY
    car_no,
    to_date
;
