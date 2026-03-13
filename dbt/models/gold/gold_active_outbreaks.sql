/*
  Gold: Active Outbreaks
  ──────────────────────
  Combines OWID disease metrics and WHO reports to show
  currently active outbreaks — defined as any disease-country
  combination with reported cases in the last 90 days.

  This is the "at a glance" model for the dashboard.
*/

WITH recent_covid AS (
    SELECT
        country_name,
        country_iso2,
        country_iso3,
        who_region,
        disease_id,
        MAX(report_date)                                AS latest_report_date,
        MAX(total_cases)                                AS latest_total_cases,
        MAX(total_deaths)                               AS latest_total_deaths,
        -- Get the average new cases over the last 7 days for trend
        AVG(CASE WHEN report_date >= CURRENT_DATE - 14
                  AND report_date < CURRENT_DATE - 7
            THEN new_cases_smoothed END)                AS avg_cases_prev_week,
        AVG(CASE WHEN report_date >= CURRENT_DATE - 7
            THEN new_cases_smoothed END)                AS avg_cases_curr_week,
        'owid'                                          AS data_source
    FROM {{ ref('silver_owid_covid') }}
    WHERE report_date >= CURRENT_DATE - 90
    GROUP BY country_name, country_iso2, country_iso3, who_region, disease_id
),

recent_mpox AS (
    SELECT
        country_name,
        country_iso2,
        country_iso3,
        who_region,
        disease_id,
        MAX(report_date)                                AS latest_report_date,
        MAX(total_cases)                                AS latest_total_cases,
        MAX(total_deaths)                               AS latest_total_deaths,
        AVG(CASE WHEN report_date >= CURRENT_DATE - 14
                  AND report_date < CURRENT_DATE - 7
            THEN new_cases_smoothed END)                AS avg_cases_prev_week,
        AVG(CASE WHEN report_date >= CURRENT_DATE - 7
            THEN new_cases_smoothed END)                AS avg_cases_curr_week,
        'owid'                                          AS data_source
    FROM {{ ref('silver_owid_mpox') }}
    WHERE report_date >= CURRENT_DATE - 90
    GROUP BY country_name, country_iso2, country_iso3, who_region, disease_id
),

combined AS (
    SELECT * FROM recent_covid
    UNION ALL
    SELECT * FROM recent_mpox
)

SELECT
    *,
    -- Trend direction based on week-over-week comparison
    CASE
        WHEN avg_cases_curr_week IS NULL OR avg_cases_prev_week IS NULL THEN 'unknown'
        WHEN avg_cases_prev_week = 0 AND avg_cases_curr_week > 0 THEN 'accelerating'
        WHEN avg_cases_prev_week = 0 THEN 'stable'
        WHEN (avg_cases_curr_week / NULLIF(avg_cases_prev_week, 0)) > 1.2 THEN 'accelerating'
        WHEN (avg_cases_curr_week / NULLIF(avg_cases_prev_week, 0)) < 0.8 THEN 'decelerating'
        ELSE 'stable'
    END AS trend_direction,

    -- Days since the most recent data point
    CURRENT_DATE - latest_report_date                   AS days_since_last_report

FROM combined
WHERE latest_total_cases > 0