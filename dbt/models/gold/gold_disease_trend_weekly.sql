/*
  Gold: Disease Trend Weekly
  ──────────────────────────
  Aggregates case and death counts into weekly buckets
  by disease and WHO region. Includes rolling averages
  and week-over-week growth rates.

  This powers time-series charts on the dashboard.
*/

WITH daily_data AS (
    SELECT disease_id, who_region, report_date, new_cases, new_deaths
    FROM {{ ref('silver_owid_covid') }}
    WHERE report_date IS NOT NULL

    UNION ALL

    SELECT disease_id, who_region, report_date, new_cases, new_deaths
    FROM {{ ref('silver_owid_mpox') }}
    WHERE report_date IS NOT NULL
),

weekly AS (
    SELECT
        disease_id,
        who_region,
        -- DATE_TRUNC to Monday of each week
        DATE_TRUNC('week', report_date)::DATE           AS week_start,
        SUM(COALESCE(new_cases, 0))                     AS weekly_cases,
        SUM(COALESCE(new_deaths, 0))                    AS weekly_deaths,
        COUNT(DISTINCT report_date)                     AS days_with_data
    FROM daily_data
    GROUP BY disease_id, who_region, DATE_TRUNC('week', report_date)
)

SELECT
    w.*,

    -- 4-week rolling average (current week + 3 prior weeks)
    AVG(weekly_cases) OVER (
        PARTITION BY disease_id, who_region
        ORDER BY week_start
        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
    )                                                   AS rolling_avg_cases_4w,

    AVG(weekly_deaths) OVER (
        PARTITION BY disease_id, who_region
        ORDER BY week_start
        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
    )                                                   AS rolling_avg_deaths_4w,

    -- Week-over-week growth rate
    LAG(weekly_cases) OVER (
        PARTITION BY disease_id, who_region
        ORDER BY week_start
    )                                                   AS prev_week_cases,

    CASE
        WHEN LAG(weekly_cases) OVER (
            PARTITION BY disease_id, who_region
            ORDER BY week_start
        ) > 0
        THEN ROUND(
            (weekly_cases - LAG(weekly_cases) OVER (
                PARTITION BY disease_id, who_region
                ORDER BY week_start
            ))::NUMERIC
            / LAG(weekly_cases) OVER (
                PARTITION BY disease_id, who_region
                ORDER BY week_start
            ) * 100, 2
        )
    END                                                 AS wow_growth_pct

FROM weekly w