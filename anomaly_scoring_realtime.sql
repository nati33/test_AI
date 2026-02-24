begin;

------------------------------------------------------------------------
-- ANOMALY SCORING – REAL-TIME
--
-- Pipeline:
--   RT-1  Aggregate live enter counts at each interval granularity
--         (only Regular + stable shops that have a baseline)
--   RT-2  Score each interval against the pre-computed baseline
--         (natis.enter_final_output_statsitic_anomaly_enter)
--   RT-3  Union all granularities into one anomaly-scoring table
--
-- Anomaly methods used per row:
--   z_score          (X_t - μ) / σ  — Gaussian approximation, always computed
--   flag_zscore      |z| > 3.0
--
--   lower_fence      P25 - 1.5 × IQR
--   upper_fence      P75 + 1.5 × IQR
--   flag_iqr         X_t outside Tukey fences
--
--   cusum_k          reference / slack value  = μ / ln(2)  (~1.44 × μ)
--   cusum_h          decision interval        = 4 × σ
--   cusum_increment  X_t - cusum_k            (accumulate externally for true CUSUM)
--   cusum_running    windowed ΣΔ within day   (SQL approximation; resets cross-day)
--
--   nb_r / nb_p      passed through for downstream NB p-value (Python / UDF)
--   is_overdispersed 1 → use NB,  0 → use Poisson
--
--   anomaly_score    0-3  count of flags triggered
--   anomaly_level    'none' / 'low' / 'medium' / 'high'
--
-- RT window: last 2 days  (getdate() - 2)
-- Change the constant to widen / narrow the look-back.
------------------------------------------------------------------------


------------------------------------------------------------------------
-- RT-1a  Live counts – 10 minutes
------------------------------------------------------------------------
drop table if exists natis.rt_enter_10_minutes;
create table natis.rt_enter_10_minutes as
WITH active_shops AS (
    SELECT shopid
    FROM natis.enter_shopid_segments
    WHERE segment_interval = '10M'
      AND segment_tenure   = 'Regular'
      AND unstable_ind     = 0
),
recent_enters AS (
    SELECT
        k.shopid,
        DATE(k.timestamp)   AS date_key,
        dd.business_day,
        k.timestamp
    FROM events.canary_parkinglot_enter k
    JOIN active_shops               a  ON k.shopid  = a.shopid
    JOIN dwh.dim_dates              dd ON DATE(k.timestamp) = dd.date
    WHERE DATE(k.timestamp) >= GETDATE() - 2
),
shop_days AS (
    SELECT DISTINCT shopid, date_key, business_day
    FROM recent_enters
),
slots AS (
    SELECT
        sd.shopid,
        sd.date_key,
        sd.business_day,
        vhi.start_time_interval,
        vhi.end_time_interval
    FROM shop_days sd
    CROSS JOIN statistic.vector_10_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    sl.shopid,
    sl.date_key,
    sl.business_day,
    sl.start_time_interval,
    sl.end_time_interval,
    '10M' AS selected_time_interval,
    COALESCE(COUNT(DISTINCT re.timestamp), 0) AS x_t
FROM slots sl
LEFT JOIN recent_enters re
    ON  sl.shopid    = re.shopid
    AND sl.date_key  = re.date_key
    AND re.timestamp::TIME >= sl.start_time_interval
    AND re.timestamp::TIME <  sl.end_time_interval
GROUP BY sl.shopid, sl.date_key, sl.business_day,
         sl.start_time_interval, sl.end_time_interval
;


------------------------------------------------------------------------
-- RT-1b  Live counts – 30 minutes
------------------------------------------------------------------------
drop table if exists natis.rt_enter_30_minutes;
create table natis.rt_enter_30_minutes as
WITH active_shops AS (
    SELECT shopid
    FROM natis.enter_shopid_segments
    WHERE segment_interval = '30M'
      AND segment_tenure   = 'Regular'
      AND unstable_ind     = 0
),
recent_enters AS (
    SELECT
        k.shopid,
        DATE(k.timestamp)   AS date_key,
        dd.business_day,
        k.timestamp
    FROM events.canary_parkinglot_enter k
    JOIN active_shops               a  ON k.shopid  = a.shopid
    JOIN dwh.dim_dates              dd ON DATE(k.timestamp) = dd.date
    WHERE DATE(k.timestamp) >= GETDATE() - 2
),
shop_days AS (
    SELECT DISTINCT shopid, date_key, business_day
    FROM recent_enters
),
slots AS (
    SELECT
        sd.shopid,
        sd.date_key,
        sd.business_day,
        vhi.start_time_interval,
        vhi.end_time_interval
    FROM shop_days sd
    CROSS JOIN statistic.vector_30_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    sl.shopid,
    sl.date_key,
    sl.business_day,
    sl.start_time_interval,
    sl.end_time_interval,
    '30M' AS selected_time_interval,
    COALESCE(COUNT(DISTINCT re.timestamp), 0) AS x_t
FROM slots sl
LEFT JOIN recent_enters re
    ON  sl.shopid    = re.shopid
    AND sl.date_key  = re.date_key
    AND re.timestamp::TIME >= sl.start_time_interval
    AND re.timestamp::TIME <  sl.end_time_interval
GROUP BY sl.shopid, sl.date_key, sl.business_day,
         sl.start_time_interval, sl.end_time_interval
;


------------------------------------------------------------------------
-- RT-1c  Live counts – 60 minutes
------------------------------------------------------------------------
drop table if exists natis.rt_enter_60_minutes;
create table natis.rt_enter_60_minutes as
WITH active_shops AS (
    SELECT shopid
    FROM natis.enter_shopid_segments
    WHERE segment_interval = '1H'
      AND segment_tenure   = 'Regular'
      AND unstable_ind     = 0
),
recent_enters AS (
    SELECT
        k.shopid,
        DATE(k.timestamp)   AS date_key,
        dd.business_day,
        k.timestamp
    FROM events.canary_parkinglot_enter k
    JOIN active_shops               a  ON k.shopid  = a.shopid
    JOIN dwh.dim_dates              dd ON DATE(k.timestamp) = dd.date
    WHERE DATE(k.timestamp) >= GETDATE() - 2
),
shop_days AS (
    SELECT DISTINCT shopid, date_key, business_day
    FROM recent_enters
),
slots AS (
    SELECT
        sd.shopid,
        sd.date_key,
        sd.business_day,
        vhi.start_time_interval,
        vhi.end_time_interval
    FROM shop_days sd
    CROSS JOIN statistic.vector_60_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    sl.shopid,
    sl.date_key,
    sl.business_day,
    sl.start_time_interval,
    sl.end_time_interval,
    '1H' AS selected_time_interval,
    COALESCE(COUNT(DISTINCT re.timestamp), 0) AS x_t
FROM slots sl
LEFT JOIN recent_enters re
    ON  sl.shopid    = re.shopid
    AND sl.date_key  = re.date_key
    AND re.timestamp::TIME >= sl.start_time_interval
    AND re.timestamp::TIME <  sl.end_time_interval
GROUP BY sl.shopid, sl.date_key, sl.business_day,
         sl.start_time_interval, sl.end_time_interval
;


------------------------------------------------------------------------
-- RT-1d  Live counts – 24 hours
------------------------------------------------------------------------
drop table if exists natis.rt_enter_24_hours;
create table natis.rt_enter_24_hours as
WITH active_shops AS (
    SELECT shopid
    FROM natis.enter_shopid_segments
    WHERE segment_interval = '24H'
      AND segment_tenure   = 'Regular'
      AND unstable_ind     = 0
),
recent_enters AS (
    SELECT
        k.shopid,
        DATE(k.timestamp)   AS date_key,
        dd.business_day,
        k.timestamp
    FROM events.canary_parkinglot_enter k
    JOIN active_shops               a  ON k.shopid  = a.shopid
    JOIN dwh.dim_dates              dd ON DATE(k.timestamp) = dd.date
    WHERE DATE(k.timestamp) >= GETDATE() - 2
),
shop_days AS (
    SELECT DISTINCT shopid, date_key, business_day
    FROM recent_enters
),
slots AS (
    SELECT
        sd.shopid,
        sd.date_key,
        sd.business_day,
        vhi.start_time_interval,
        vhi.end_time_interval
    FROM shop_days sd
    CROSS JOIN statistic.vector_24_hours_interval_parking_lot_anomaly vhi
)
SELECT
    sl.shopid,
    sl.date_key,
    sl.business_day,
    sl.start_time_interval,
    sl.end_time_interval,
    '24H' AS selected_time_interval,
    COALESCE(COUNT(DISTINCT re.timestamp), 0) AS x_t
FROM slots sl
LEFT JOIN recent_enters re
    ON  sl.shopid    = re.shopid
    AND sl.date_key  = re.date_key
    AND re.timestamp::TIME >= sl.start_time_interval
    AND re.timestamp::TIME <  sl.end_time_interval
GROUP BY sl.shopid, sl.date_key, sl.business_day,
         sl.start_time_interval, sl.end_time_interval
;


------------------------------------------------------------------------
-- RT-2  Union all granularities, join baseline, compute anomaly scores
------------------------------------------------------------------------
drop table if exists natis.rt_anomaly_scores;
create table natis.rt_anomaly_scores as
WITH live AS (
    SELECT * FROM natis.rt_enter_10_minutes
    UNION ALL
    SELECT * FROM natis.rt_enter_30_minutes
    UNION ALL
    SELECT * FROM natis.rt_enter_60_minutes
    UNION ALL
    SELECT * FROM natis.rt_enter_24_hours
),
scored AS (
    SELECT
        -- ── identifiers ──────────────────────────────────────────────────
        l.shopid,
        b.shop_name,
        b.vendor_name,
        l.date_key,
        l.business_day,
        l.start_time_interval,
        l.end_time_interval,
        l.selected_time_interval,

        -- ── live observation ─────────────────────────────────────────────
        l.x_t,

        -- ── baseline context ─────────────────────────────────────────────
        b.enter_mean,
        b.enter_std,
        b.enter_median,
        b.enter_p25,
        b.enter_p75,
        b.enter_iqr,
        b.total_observation      AS baseline_observation_count,

        -- ── Z-score ──────────────────────────────────────────────────────
        CASE
            WHEN b.enter_std > 0
            THEN (l.x_t - b.enter_mean) / b.enter_std
            ELSE NULL
        END                                                   AS z_score,

        -- ── IQR Tukey fences ─────────────────────────────────────────────
        b.enter_p25 - 1.5 * b.enter_iqr                      AS lower_fence,
        b.enter_p75 + 1.5 * b.enter_iqr                      AS upper_fence,

        -- ── CUSUM parameters (for external accumulation or Python) ────────
        --   k  = reference value (slack): midpoint between μ and 2μ
        --   H  = decision interval calibrated to ARL ~500
        b.enter_mean / ln(2)                                  AS cusum_k,
        b.enter_std  * 4                                      AS cusum_h,
        --   increment = X_t - k  (sum these in order to get true CUSUM S_t)
        l.x_t - (b.enter_mean / ln(2))                       AS cusum_increment,
        --   running windowed sum within the day (SQL approximation of CUSUM)
        --   Note: does not apply the max(0,.) reset — use Python for true CUSUM
        SUM(l.x_t - (b.enter_mean / ln(2))) OVER (
            PARTITION BY l.shopid, l.date_key, l.selected_time_interval
            ORDER BY l.start_time_interval
            ROWS UNBOUNDED PRECEDING
        )                                                     AS cusum_running,

        -- ── NB / Poisson parameters (for downstream p-value) ─────────────
        b.is_overdispersed,
        b.nb_r,
        b.nb_p,
        b.enter_cv,

        -- ── individual flags ─────────────────────────────────────────────
        CASE
            WHEN b.enter_std > 0
             AND ABS((l.x_t - b.enter_mean) / b.enter_std) > 3.0
            THEN 1 ELSE 0
        END                                                   AS flag_zscore,

        CASE
            WHEN l.x_t > b.enter_p75 + 1.5 * b.enter_iqr
              OR l.x_t < b.enter_p25 - 1.5 * b.enter_iqr
            THEN 1 ELSE 0
        END                                                   AS flag_iqr,

        -- CUSUM flag: running sum has crossed decision interval H
        CASE
            WHEN SUM(l.x_t - (b.enter_mean / ln(2))) OVER (
                     PARTITION BY l.shopid, l.date_key, l.selected_time_interval
                     ORDER BY l.start_time_interval
                     ROWS UNBOUNDED PRECEDING
                 ) > b.enter_std * 4
            THEN 1 ELSE 0
        END                                                   AS flag_cusum

    FROM live l
    JOIN natis.enter_final_output_statsitic_anomaly_enter b
        ON  l.shopid              = b.shop_id
        AND l.start_time_interval = b.start_time_interval
        AND l.business_day        = b.business_day
        AND l.selected_time_interval = b.selected_time_interval
)
SELECT
    *,

    -- ── composite score (0 – 3 flags) ────────────────────────────────────
    flag_zscore + flag_iqr + flag_cusum                       AS anomaly_score,

    -- ── human-readable severity level ────────────────────────────────────
    CASE
        WHEN flag_zscore + flag_iqr + flag_cusum = 0 THEN 'none'
        WHEN flag_zscore + flag_iqr + flag_cusum = 1 THEN 'low'
        WHEN flag_zscore + flag_iqr + flag_cusum = 2 THEN 'medium'
        ELSE                                               'high'
    END                                                       AS anomaly_level,

    -- ── direction of anomaly ─────────────────────────────────────────────
    CASE
        WHEN x_t > enter_mean THEN 'spike'
        WHEN x_t < enter_mean THEN 'drop'
        ELSE                       'normal'
    END                                                       AS anomaly_direction

FROM scored
;

end;
