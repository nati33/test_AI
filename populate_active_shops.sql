begin;

truncate table statistic.active_pl;
insert into statistic.active_pl
SELECT id as shopid FROM mrr.mcp_Shop
        WHERE UrlWs IS NOT NULL AND UrlWs <> ''
        AND Shop_User_Name IS NOT NULL AND Shop_User_Name <> ''
        AND Shop_Password IS NOT NULL AND Shop_Password <> ''
        ;


truncate table statistic.enter_shopid_interval_mapping;
insert into statistic.enter_shopid_interval_mapping
select shopid, business_day,
avg(freq)                        as avg_daily_enter,
stddev_pop(freq)                 as std_daily_enter,
min(enter_date)                  as first_enter,
max(enter_date)                  as last_enter,
count(distinct enter_date)       as total_observation
from
(
    select shopid,
           dd.business_day,
           date(a.timestamp)  as enter_date,
           count(*)           as freq
    from events.canary_parkinglot_enter a
    join dwh.dim_dates dd ON DATE(a.timestamp) = dd.date
    where date(timestamp) >= getdate() - 240
    group by 1, 2, 3
) a
group by 1, 2
;


----------------------------------------------------
truncate table statistic.enter_shopid_segments;
insert into statistic.enter_shopid_segments
select
    a.shopid,
    case when avg_daily_enter is null        then 'no_enter_data'
         when avg_daily_enter < 25           then '24H'
         when avg_daily_enter < 200          then '1H'
         when avg_daily_enter < 600          then '30M'
         else                                     '10M' end  as segment_interval,
    case when last_enter < getdate() - 30   then 'Not Active'
         when total_observation < 30         then 'New'
         else                                     'Regular'  end as segment_tenure,
    case when std_daily_enter / avg_daily_enter >= 1.3 then 1 else 0 end as unstable_ind
from statistic.active_pl a
left join (
    select * from statistic.enter_shopid_interval_mapping where business_day = 1
) b on a.shopid = b.shopid
;


-------------------------------------------------------------------
-- STEP 1: raw interval counts (10 minutes)
-------------------------------------------------------------------
truncate table statistic.enter_step_1_anomaly_10_minutes;
insert into statistic.enter_step_1_anomaly_10_minutes
WITH shop_min_max_dates AS (
    SELECT shopid,
           MIN(DATE(timestamp)) AS min_date,
           MAX(DATE(timestamp)) AS max_date
    FROM events.canary_parkinglot_enter
    where date(timestamp) >= getdate() - 240
    GROUP BY shopid
),
days_vector AS (
    SELECT DISTINCT smd.shopid, dd.date AS date_key
    FROM shop_min_max_dates smd
    JOIN dwh.dim_dates dd ON dd.date BETWEEN smd.min_date AND smd.max_date
),
enter_vector AS (
    SELECT k.shopid, k.timestamp,
           sh.shop_name, sh.vendor_id, mv.vendor_name,
           dd.date AS date_key, dd.business_day,
           dtp.latitude, dtp.longitude
    FROM events.canary_parkinglot_enter k
    JOIN statistic.enter_shopid_segments b ON k.shopid = b.shopid
    JOIN (
        SELECT * FROM mrr.mcp_Shop
        WHERE UrlWs IS NOT NULL AND UrlWs <> ''
        AND Shop_User_Name IS NOT NULL AND Shop_User_Name <> ''
        AND Shop_Password IS NOT NULL AND Shop_Password <> ''
    ) sh ON k.shopid = sh.id
    JOIN mrr.mcp_vendors mv ON sh.vendor_id = mv.id
    JOIN dwh.dim_dates dd ON DATE(k.timestamp) = dd.date
    LEFT JOIN dwh.dwh_transaction_places dtp ON k.shopid = dtp.transaction_place_opertional_id
    where b.segment_interval = '10M'
    and b.segment_tenure = 'Regular'
    and vendor_name != 'חניונים וירטואלים'
    and b.unstable_ind = 0
),
shopid_vector AS (
    SELECT DISTINCT shopid FROM enter_vector
),
shops_intervals AS (
    SELECT DISTINCT dv.shopid, dv.date_key,
                    vhi.start_time_interval, vhi.end_time_interval
    FROM days_vector dv
    JOIN shopid_vector sv ON dv.shopid = sv.shopid
    CROSS JOIN statistic.vector_10_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    si.shopid, sh.shop_name, mv.vendor_name,
    si.date_key, si.start_time_interval, si.end_time_interval,
    dd.business_day, dtp.longitude, dtp.latitude,
    COALESCE(COUNT(DISTINCT ev.timestamp), 0) AS enter_count
FROM shops_intervals si
LEFT JOIN enter_vector ev
    ON si.shopid = ev.shopid
    AND si.date_key = ev.date_key
    AND ev.timestamp::TIME >= si.start_time_interval
    AND ev.timestamp::TIME <  si.end_time_interval
JOIN  dwh.dim_dates dd ON si.date_key = dd.date
JOIN  mrr.mcp_Shop  sh ON si.shopid   = sh.id
JOIN  mrr.mcp_vendors mv ON sh.vendor_id = mv.id
LEFT JOIN (select * from dwh.dwh_transaction_places where transaction_type_id = 2) dtp
    ON si.shopid = dtp.transaction_place_opertional_id
GROUP BY si.shopid, sh.shop_name, mv.vendor_name, si.date_key,
         si.start_time_interval, si.end_time_interval, dd.business_day,
         dtp.longitude, dtp.latitude
ORDER BY si.shopid, si.date_key, si.start_time_interval
;


----------------------------------------------
-- STEP 1: raw interval counts (30 minutes)
----------------------------------------------
truncate table statistic.enter_step_1_anomaly_enter_30_minutes;
insert into statistic.enter_step_1_anomaly_enter_30_minutes
WITH shop_min_max_dates AS (
    SELECT shopid,
           MIN(DATE(timestamp)) AS min_date,
           MAX(DATE(timestamp)) AS max_date
    FROM events.canary_parkinglot_enter
    where date(timestamp) >= getdate() - 240
    GROUP BY shopid
),
days_vector AS (
    SELECT DISTINCT smd.shopid, dd.date AS date_key
    FROM shop_min_max_dates smd
    JOIN dwh.dim_dates dd ON dd.date BETWEEN smd.min_date AND smd.max_date
),
enter_vector AS (
    SELECT k.shopid, k.timestamp,
           sh.shop_name, sh.vendor_id, mv.vendor_name,
           dd.date AS date_key, dd.business_day,
           dtp.latitude, dtp.longitude
    FROM events.canary_parkinglot_enter k
    JOIN statistic.enter_shopid_segments b ON k.shopid = b.shopid
    JOIN (
        SELECT * FROM mrr.mcp_Shop
        WHERE UrlWs IS NOT NULL AND UrlWs <> ''
        AND Shop_User_Name IS NOT NULL AND Shop_User_Name <> ''
        AND Shop_Password IS NOT NULL AND Shop_Password <> ''
    ) sh ON k.shopid = sh.id
    JOIN mrr.mcp_vendors mv ON sh.vendor_id = mv.id
    JOIN dwh.dim_dates dd ON DATE(k.timestamp) = dd.date
    LEFT JOIN dwh.dwh_transaction_places dtp ON k.shopid = dtp.transaction_place_opertional_id
    where b.segment_interval = '30M'
    and b.segment_tenure = 'Regular'
    and vendor_name != 'חניונים וירטואלים'
    and b.unstable_ind = 0
),
shopid_vector AS (
    SELECT DISTINCT shopid FROM enter_vector
),
shops_intervals AS (
    SELECT DISTINCT dv.shopid, dv.date_key,
                    vhi.start_time_interval, vhi.end_time_interval
    FROM days_vector dv
    JOIN shopid_vector sv ON dv.shopid = sv.shopid
    CROSS JOIN statistic.vector_30_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    si.shopid, sh.shop_name, mv.vendor_name,
    si.date_key, si.start_time_interval, si.end_time_interval,
    dd.business_day, dtp.longitude, dtp.latitude,
    COALESCE(COUNT(DISTINCT ev.timestamp), 0) AS enter_count
FROM shops_intervals si
LEFT JOIN enter_vector ev
    ON si.shopid = ev.shopid
    AND si.date_key = ev.date_key
    AND ev.timestamp::TIME >= si.start_time_interval
    AND ev.timestamp::TIME <  si.end_time_interval
JOIN  dwh.dim_dates dd ON si.date_key = dd.date
JOIN  mrr.mcp_Shop  sh ON si.shopid   = sh.id
JOIN  mrr.mcp_vendors mv ON sh.vendor_id = mv.id
LEFT JOIN (select * from dwh.dwh_transaction_places where transaction_type_id = 2) dtp
    ON si.shopid = dtp.transaction_place_opertional_id
GROUP BY si.shopid, sh.shop_name, mv.vendor_name, si.date_key,
         si.start_time_interval, si.end_time_interval, dd.business_day,
         dtp.longitude, dtp.latitude
ORDER BY si.shopid, si.date_key, si.start_time_interval
;


----------------------------------------------
-- STEP 1: raw interval counts (60 minutes)
----------------------------------------------
truncate table statistic.enter_step_1_anomaly_enter_60_minutes;
insert into statistic.enter_step_1_anomaly_enter_60_minutes
WITH shop_min_max_dates AS (
    SELECT shopid,
           MIN(DATE(timestamp)) AS min_date,
           MAX(DATE(timestamp)) AS max_date
    FROM events.canary_parkinglot_enter
    where date(timestamp) >= getdate() - 240
    GROUP BY shopid
),
days_vector AS (
    SELECT DISTINCT smd.shopid, dd.date AS date_key
    FROM shop_min_max_dates smd
    JOIN dwh.dim_dates dd ON dd.date BETWEEN smd.min_date AND smd.max_date
),
enter_vector AS (
    SELECT k.shopid, k.timestamp,
           sh.shop_name, sh.vendor_id, mv.vendor_name,
           dd.date AS date_key, dd.business_day,
           dtp.latitude, dtp.longitude
    FROM events.canary_parkinglot_enter k
    JOIN statistic.enter_shopid_segments b ON k.shopid = b.shopid
    JOIN (
        SELECT * FROM mrr.mcp_Shop
        WHERE UrlWs IS NOT NULL AND UrlWs <> ''
        AND Shop_User_Name IS NOT NULL AND Shop_User_Name <> ''
        AND Shop_Password IS NOT NULL AND Shop_Password <> ''
    ) sh ON k.shopid = sh.id
    JOIN mrr.mcp_vendors mv ON sh.vendor_id = mv.id
    JOIN dwh.dim_dates dd ON DATE(k.timestamp) = dd.date
    LEFT JOIN dwh.dwh_transaction_places dtp ON k.shopid = dtp.transaction_place_opertional_id
    where b.segment_interval = '1H'
    and b.segment_tenure = 'Regular'
    and vendor_name != 'חניונים וירטואלים'
    and b.unstable_ind = 0
),
shopid_vector AS (
    SELECT DISTINCT shopid FROM enter_vector
),
shops_intervals AS (
    SELECT DISTINCT dv.shopid, dv.date_key,
                    vhi.start_time_interval, vhi.end_time_interval
    FROM days_vector dv
    JOIN shopid_vector sv ON dv.shopid = sv.shopid
    CROSS JOIN statistic.vector_60_minutes_interval_parking_lot_anomaly vhi
)
SELECT
    si.shopid, sh.shop_name, mv.vendor_name,
    si.date_key, si.start_time_interval, si.end_time_interval,
    dd.business_day, dtp.longitude, dtp.latitude,
    COALESCE(COUNT(DISTINCT ev.timestamp), 0) AS enter_count
FROM shops_intervals si
LEFT JOIN enter_vector ev
    ON si.shopid = ev.shopid
    AND si.date_key = ev.date_key
    AND ev.timestamp::TIME >= si.start_time_interval
    AND ev.timestamp::TIME <  si.end_time_interval
JOIN  dwh.dim_dates dd ON si.date_key = dd.date
JOIN  mrr.mcp_Shop  sh ON si.shopid   = sh.id
JOIN  mrr.mcp_vendors mv ON sh.vendor_id = mv.id
LEFT JOIN (select * from dwh.dwh_transaction_places where transaction_type_id = 2) dtp
    ON si.shopid = dtp.transaction_place_opertional_id
GROUP BY si.shopid, sh.shop_name, mv.vendor_name, si.date_key,
         si.start_time_interval, si.end_time_interval, dd.business_day,
         dtp.longitude, dtp.latitude
ORDER BY si.shopid, si.date_key, si.start_time_interval
;


----------------------------------------------
-- STEP 1: raw interval counts (24 hours)
----------------------------------------------
truncate table statistic.enter_step_1_anomaly_enter_24_hours;
insert into statistic.enter_step_1_anomaly_enter_24_hours
WITH shop_min_max_dates AS (
    SELECT shopid,
           MIN(DATE(timestamp)) AS min_date,
           MAX(DATE(timestamp)) AS max_date
    FROM events.canary_parkinglot_enter
    where date(timestamp) >= getdate() - 240
    GROUP BY shopid
),
days_vector AS (
    SELECT DISTINCT smd.shopid, dd.date AS date_key
    FROM shop_min_max_dates smd
    JOIN dwh.dim_dates dd ON dd.date BETWEEN smd.min_date AND smd.max_date
),
enter_vector AS (
    SELECT k.shopid, k.timestamp,
           sh.shop_name, sh.vendor_id, mv.vendor_name,
           dd.date AS date_key, dd.business_day,
           dtp.latitude, dtp.longitude
    FROM events.canary_parkinglot_enter k
    JOIN statistic.enter_shopid_segments b ON k.shopid = b.shopid
    JOIN (
        SELECT * FROM mrr.mcp_Shop
        WHERE UrlWs IS NOT NULL AND UrlWs <> ''
        AND Shop_User_Name IS NOT NULL AND Shop_User_Name <> ''
        AND Shop_Password IS NOT NULL AND Shop_Password <> ''
    ) sh ON k.shopid = sh.id
    JOIN mrr.mcp_vendors mv ON sh.vendor_id = mv.id
    JOIN dwh.dim_dates dd ON DATE(k.timestamp) = dd.date
    LEFT JOIN dwh.dwh_transaction_places dtp ON k.shopid = dtp.transaction_place_opertional_id
    where b.segment_interval = '24H'
    and b.segment_tenure = 'Regular'
    and vendor_name != 'חניונים וירטואלים'
    and b.unstable_ind = 0
),
shopid_vector AS (
    SELECT DISTINCT shopid FROM enter_vector
),
shops_intervals AS (
    SELECT DISTINCT dv.shopid, dv.date_key,
                    vhi.start_time_interval, vhi.end_time_interval
    FROM days_vector dv
    JOIN shopid_vector sv ON dv.shopid = sv.shopid
    CROSS JOIN statistic.vector_24_hours_interval_parking_lot_anomaly vhi
)
SELECT
    si.shopid, sh.shop_name, mv.vendor_name,
    si.date_key, si.start_time_interval, si.end_time_interval,
    dd.business_day, dtp.longitude, dtp.latitude,
    COALESCE(COUNT(DISTINCT ev.timestamp), 0) AS enter_count,
    COALESCE(
        LAG(COALESCE(COUNT(DISTINCT ev.timestamp), 0)) OVER (
            PARTITION BY si.shopid ORDER BY si.date_key
        ), 0
    ) AS lag_1_enter_count
FROM shops_intervals si
LEFT JOIN enter_vector ev
    ON si.shopid = ev.shopid
    AND si.date_key = ev.date_key
JOIN  dwh.dim_dates dd ON si.date_key = dd.date
JOIN  mrr.mcp_Shop  sh ON si.shopid   = sh.id
JOIN  mrr.mcp_vendors mv ON sh.vendor_id = mv.id
LEFT JOIN (select * from dwh.dwh_transaction_places where transaction_type_id = 2) dtp
    ON si.shopid = dtp.transaction_place_opertional_id
GROUP BY si.shopid, sh.shop_name, mv.vendor_name, si.date_key,
         si.start_time_interval, si.end_time_interval, dd.business_day,
         dtp.longitude, dtp.latitude
ORDER BY si.shopid, si.date_key, si.start_time_interval
;


--------------------------------------------------------------------------------------
-- STEP 2: aggregate statistics per (shopid, interval slot, business_day)
--
-- New columns vs original:
--   enter_var        – population variance  → needed by NB and CUSUM
--   enter_sum        – total count           → MLE fitting of NB
--   enter_max        – maximum per slot      → range / outlier context
--   enter_min        – minimum per slot
--   enter_median     – median (P50)          → robust location for NB
--   enter_p25        – 1st quartile (P25)    → IQR-based spread
--   enter_p75        – 3rd quartile (P75)
--   enter_lag_var    – lagged variance       → sequential CUSUM
--
-- Derived in final output:
--   nb_r             – NB dispersion param   = μ² / (σ²−μ)   [valid when σ²>μ]
--   nb_p             – NB success prob       = μ / σ²         [valid when σ²>μ]
--   enter_cv         – coeff of variation    = σ / μ
--   is_overdispersed – flag: σ² > μ
--------------------------------------------------------------------------------------

truncate table statistic.enter_step_2_anomaly_statistic_10_minutes;
insert into statistic.enter_step_2_anomaly_statistic_10_minutes
SELECT
    shopid, shop_name, vendor_name,
    start_time_interval,
    end_time_interval,
    business_day,
    '10M'             as selected_time_interval,
    'count_entrance'  as measure_name,
    longitude, latitude,
    -- location
    SUM(enter_count) / COUNT(*)::FLOAT                       AS enter_mean,
    STDDEV_POP(enter_count)                                  AS enter_std,
    -- NEW: variance and distribution shape
    VAR_POP(enter_count)                                     AS enter_var,
    SUM(enter_count)                                         AS enter_sum,
    MAX(enter_count)                                         AS enter_max,
    MIN(enter_count)                                         AS enter_min,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY enter_count) AS enter_median,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY enter_count) AS enter_p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY enter_count) AS enter_p75,
    -- zero inflation
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END)        AS zero_interval,
    COUNT(*)                                                  AS total_observation,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END) / COUNT(*)::FLOAT AS zero_prop,
    -- lag statistics (sequential CUSUM baseline)
    LAG(SUM(enter_count) / COUNT(*)::FLOAT) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_mean,
    LAG(STDDEV_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_std,
    LAG(VAR_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_var
FROM statistic.enter_step_1_anomaly_10_minutes
GROUP BY shopid, shop_name, vendor_name,
         start_time_interval, end_time_interval, business_day,
         longitude, latitude
ORDER BY shopid, start_time_interval
;


truncate table statistic.enter_step_2_anomaly_statistic_30_minutes;
insert into statistic.enter_step_2_anomaly_statistic_30_minutes
SELECT
    shopid, shop_name, vendor_name,
    start_time_interval,
    end_time_interval,
    business_day,
    '30M'             as selected_time_interval,
    'count_entrance'  as measure_name,
    longitude, latitude,
    SUM(enter_count) / COUNT(*)::FLOAT                       AS enter_mean,
    STDDEV_POP(enter_count)                                  AS enter_std,
    VAR_POP(enter_count)                                     AS enter_var,
    SUM(enter_count)                                         AS enter_sum,
    MAX(enter_count)                                         AS enter_max,
    MIN(enter_count)                                         AS enter_min,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY enter_count) AS enter_median,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY enter_count) AS enter_p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY enter_count) AS enter_p75,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END)        AS zero_interval,
    COUNT(*)                                                  AS total_observation,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END) / COUNT(*)::FLOAT AS zero_prop,
    LAG(SUM(enter_count) / COUNT(*)::FLOAT) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_mean,
    LAG(STDDEV_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_std,
    LAG(VAR_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_var
FROM statistic.enter_step_1_anomaly_enter_30_minutes
GROUP BY shopid, shop_name, vendor_name,
         start_time_interval, end_time_interval, business_day,
         longitude, latitude
ORDER BY shopid, start_time_interval
;


truncate table statistic.enter_step_2_anomaly_statistic_60_minutes;
insert into statistic.enter_step_2_anomaly_statistic_60_minutes
SELECT
    shopid, shop_name, vendor_name,
    start_time_interval,
    end_time_interval,
    business_day,
    '1H'              as selected_time_interval,
    'count_entrance'  as measure_name,
    longitude, latitude,
    SUM(enter_count) / COUNT(*)::FLOAT                       AS enter_mean,
    STDDEV_POP(enter_count)                                  AS enter_std,
    VAR_POP(enter_count)                                     AS enter_var,
    SUM(enter_count)                                         AS enter_sum,
    MAX(enter_count)                                         AS enter_max,
    MIN(enter_count)                                         AS enter_min,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY enter_count) AS enter_median,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY enter_count) AS enter_p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY enter_count) AS enter_p75,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END)        AS zero_interval,
    COUNT(*)                                                  AS total_observation,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END) / COUNT(*)::FLOAT AS zero_prop,
    LAG(SUM(enter_count) / COUNT(*)::FLOAT) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_mean,
    LAG(STDDEV_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_std,
    LAG(VAR_POP(enter_count)) OVER (
        PARTITION BY shopid, business_day ORDER BY start_time_interval
    )                                                        AS enter_lag_var
FROM statistic.enter_step_1_anomaly_enter_60_minutes
GROUP BY shopid, shop_name, vendor_name,
         start_time_interval, end_time_interval, business_day,
         longitude, latitude
ORDER BY shopid, start_time_interval
;


truncate table statistic.enter_step_2_anomaly_statistic_24_hours;
insert into statistic.enter_step_2_anomaly_statistic_24_hours
SELECT
    shopid, shop_name, vendor_name,
    start_time_interval,
    end_time_interval,
    business_day,
    '24H'             as selected_time_interval,
    'count_entrance'  as measure_name,
    longitude, latitude,
    SUM(enter_count) / COUNT(*)::FLOAT                       AS enter_mean,
    STDDEV_POP(enter_count)                                  AS enter_std,
    VAR_POP(enter_count)                                     AS enter_var,
    SUM(enter_count)                                         AS enter_sum,
    MAX(enter_count)                                         AS enter_max,
    MIN(enter_count)                                         AS enter_min,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY enter_count) AS enter_median,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY enter_count) AS enter_p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY enter_count) AS enter_p75,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END)        AS zero_interval,
    COUNT(*)                                                  AS total_observation,
    SUM(CASE WHEN enter_count = 0 THEN 1 ELSE 0 END) / COUNT(*)::FLOAT AS zero_prop,
    0.0  AS enter_lag_mean,
    0.0  AS enter_lag_std,
    0.0  AS enter_lag_var
FROM statistic.enter_step_1_anomaly_enter_24_hours
GROUP BY shopid, shop_name, vendor_name,
         start_time_interval, end_time_interval, business_day,
         longitude, latitude
ORDER BY shopid, start_time_interval
;


-----------------------------------------------------
truncate table statistic.enter_union_statistic_enter_anomaly;
insert into statistic.enter_union_statistic_enter_anomaly
select * from statistic.enter_step_2_anomaly_statistic_10_minutes
union all
select * from statistic.enter_step_2_anomaly_statistic_30_minutes
union all
select * from statistic.enter_step_2_anomaly_statistic_60_minutes
union all
select * from statistic.enter_step_2_anomaly_statistic_24_hours
;


----------------------------------------------------------
-- FINAL OUTPUT
-- New derived columns for NB distribution and CUSUM:
--
--  nb_r             NB dispersion/size parameter (r, also called theta/k):
--                   r = μ² / (σ² − μ)
--                   Valid only when σ² > μ (overdispersed). NULL otherwise.
--                   Used for:  NB p-value, NB-CUSUM reference value k.
--
--  nb_p             NB success-probability parameter:
--                   p = μ / σ²  (equivalent to r / (r + μ))
--                   Valid only when σ² > μ.
--                   Used for:  NB CDF / p-value calculation.
--
--  enter_cv         Coefficient of variation = σ / μ
--                   Used for:  stability check before choosing Poisson vs NB,
--                              adaptive CUSUM slack setting.
--
--  is_overdispersed 1 when σ² > μ → NB is appropriate model.
--                   0 when σ² ≤ μ → Poisson may suffice.
--
--  enter_var        Raw population variance (carried through from step 2).
--  enter_lag_var    Lagged variance for the previous interval slot.
--  enter_sum        Total raw count across all observed days.
--  enter_max        Maximum slot count observed.
--  enter_min        Minimum slot count observed.
--  enter_median     Median slot count (robust location).
--  enter_p25        25th percentile.
--  enter_p75        75th percentile.
--  enter_iqr        Interquartile range = p75 − p25.
--
-- CUSUM note:
--   The one-sided upper Page CUSUM is:
--     S_t = max(0, S_{t-1} + X_t − k)
--   For NB(r, p) a common choice of reference value k is:
--     k = (μ_1 − μ_0) / ln(μ_1 / μ_0)   (log-likelihood ratio midpoint)
--   where μ_0 = enter_mean (baseline) and μ_1 is the target shift mean.
--   The decision interval H is typically calibrated to a desired ARL.
--   All parameters needed (enter_mean, nb_r, nb_p) are stored here.
----------------------------------------------------------
truncate table statistic.enter_final_output_statsitic_anomaly_enter;
insert into statistic.enter_final_output_statsitic_anomaly_enter
select
    shopid                           as shop_id,
    shop_name,
    start_time_interval,
    end_time_interval,
    selected_time_interval,
    -- time in seconds (for downstream ease)
    (EXTRACT(HOUR   FROM start_time_interval) * 3600 +
     EXTRACT(MINUTE FROM start_time_interval) * 60   +
     EXTRACT(SECOND FROM start_time_interval))        AS start_time_sec,
    CASE
        WHEN EXTRACT(HOUR   FROM end_time_interval) = 0
         AND EXTRACT(MINUTE FROM end_time_interval) = 0
         AND EXTRACT(SECOND FROM end_time_interval) = 0
        THEN 86400
        ELSE
            EXTRACT(HOUR   FROM end_time_interval) * 3600 +
            EXTRACT(MINUTE FROM end_time_interval) * 60   +
            EXTRACT(SECOND FROM end_time_interval)
    END                                               AS end_time_sec,
    business_day,

    -- ── location & spread ─────────────────────────────────────────────────
    enter_mean,
    enter_std,
    enter_var,
    enter_sum,
    enter_max,
    enter_min,
    enter_median,
    enter_p25,
    enter_p75,
    (enter_p75 - enter_p25)                          AS enter_iqr,

    -- coefficient of variation  (σ/μ) – used for CUSUM slack & model choice
    CASE WHEN enter_mean > 0
         THEN enter_std / enter_mean
         ELSE NULL END                               AS enter_cv,

    -- ── zero inflation ────────────────────────────────────────────────────
    zero_interval                                    AS enter_zero_count,
    zero_prop                                        AS enter_zero_prop,

    -- ── lag statistics (sequential / CUSUM baseline) ──────────────────────
    COALESCE(enter_lag_mean, enter_mean)             AS enter_lag_mean,
    COALESCE(enter_lag_std,  enter_std)              AS enter_lag_std,
    COALESCE(enter_lag_var,  enter_var)              AS enter_lag_var,

    -- ── Negative Binomial parameters ─────────────────────────────────────
    --   Valid when σ² > μ  (overdispersed count data).
    --   When σ² ≤ μ the distribution is equi- or under-dispersed;
    --   use Poisson (nb_r, nb_p will be NULL).
    CASE WHEN enter_var > enter_mean AND enter_mean > 0
         THEN POWER(enter_mean, 2) / NULLIF(enter_var - enter_mean, 0)
         ELSE NULL END                               AS nb_r,   -- size / dispersion parameter

    CASE WHEN enter_var > enter_mean AND enter_mean > 0
         THEN enter_mean / NULLIF(enter_var, 0)
         ELSE NULL END                               AS nb_p,   -- success probability

    CASE WHEN enter_var > enter_mean THEN 1 ELSE 0 END AS is_overdispersed,

    -- ── metadata ─────────────────────────────────────────────────────────
    measure_name,
    vendor_name,
    longitude,
    latitude,
    total_observation

from statistic.enter_union_statistic_enter_anomaly
;

end;
