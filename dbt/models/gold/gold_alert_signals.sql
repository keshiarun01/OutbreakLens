/*
  Gold: Alert Signals
  ───────────────────
  Flags outbreaks that need attention based on rules:
    1. SURGE: Current week cases > 2x the 4-week rolling average
    2. HIGH_MORTALITY: Death-to-case ratio above disease's typical CFR
    3. RAPID_GROWTH: Week-over-week growth exceeding 50%

  Each row is one alert for one disease-region-week combination.
  Severity is ranked: critical > high > medium.
*/

WITH trends AS (
    SELECT * FROM {{ ref('gold_disease_trend_weekly') }}
    WHERE week_start >= CURRENT_DATE - 90
),

alerts AS (
    -- SURGE alerts: cases far above rolling average
    SELECT
        t.disease_id,
        t.who_region,
        t.week_start,
        'SURGE' AS alert_type,
        'Weekly cases (' || t.weekly_cases || ') exceed 2x the 4-week average ('
            || ROUND(t.rolling_avg_cases_4w) || ')' AS alert_description,
        t.weekly_cases,
        t.rolling_avg_cases_4w,
        CASE
            WHEN t.weekly_cases > 5 * NULLIF(t.rolling_avg_cases_4w, 0) THEN 'critical'
            WHEN t.weekly_cases > 3 * NULLIF(t.rolling_avg_cases_4w, 0) THEN 'high'
            ELSE 'medium'
        END AS severity
    FROM trends t
    WHERE
        t.rolling_avg_cases_4w > 0
        AND t.weekly_cases > 2 * t.rolling_avg_cases_4w
        AND t.weekly_cases > 10  -- ignore tiny numbers

    UNION ALL

    -- RAPID_GROWTH alerts: fast week-over-week increase
    SELECT
        t.disease_id,
        t.who_region,
        t.week_start,
        'RAPID_GROWTH' AS alert_type,
        'Week-over-week growth of ' || t.wow_growth_pct || '%' AS alert_description,
        t.weekly_cases,
        t.rolling_avg_cases_4w,
        CASE
            WHEN t.wow_growth_pct > 200 THEN 'critical'
            WHEN t.wow_growth_pct > 100 THEN 'high'
            ELSE 'medium'
        END AS severity
    FROM trends t
    WHERE
        t.wow_growth_pct > 50
        AND t.weekly_cases > 10

    UNION ALL

    -- HIGH_MORTALITY alerts: deaths disproportionate to cases
    SELECT
        t.disease_id,
        t.who_region,
        t.week_start,
        'HIGH_MORTALITY' AS alert_type,
        'Weekly deaths (' || t.weekly_deaths || ') are high relative to cases ('
            || t.weekly_cases || ')' AS alert_description,
        t.weekly_cases,
        t.rolling_avg_cases_4w,
        CASE
            WHEN t.weekly_deaths > t.weekly_cases * 0.1 THEN 'critical'
            ELSE 'high'
        END AS severity
    FROM trends t
    WHERE
        t.weekly_cases > 0
        AND t.weekly_deaths > 0
        AND (t.weekly_deaths::NUMERIC / NULLIF(t.weekly_cases, 0)) > 0.05
        AND t.weekly_cases > 10
)

SELECT
    *,
    -- Overall severity ranking for sorting (1 = most severe)
    CASE severity
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
    END AS severity_rank
FROM alerts
ORDER BY severity_rank, week_start DESC