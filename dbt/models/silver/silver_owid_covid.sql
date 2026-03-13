
/*
  Silver OWID COVID-19 Metrics
  ────────────────────────────
  Cleans and types the raw COVID data from bronze.
  
  Key transformations:
    1. Cast TEXT columns to proper numeric/date types
    2. Filter out aggregate rows (like "World", "Europe")
    3. Add ISO country code by joining to location dimension
    4. Handle NULLs gracefully
*/

WITH source AS (
    SELECT * FROM {{ source('bronze', 'owid_covid') }}
),

cleaned AS (
    SELECT
        TRIM(country)                                    AS country_name,
        CASE WHEN date != '' THEN date::DATE END         AS report_date,

        -- Case metrics: cast from text to numeric
        CASE WHEN total_cases ~ '^\d+\.?\d*$'
            THEN total_cases::NUMERIC END                AS total_cases,
        CASE WHEN new_cases ~ '^-?\d+\.?\d*$'
            THEN new_cases::NUMERIC END                  AS new_cases,
        CASE WHEN new_cases_smoothed ~ '^-?\d+\.?\d*$'
            THEN new_cases_smoothed::NUMERIC END         AS new_cases_smoothed,

        -- Death metrics
        CASE WHEN total_deaths ~ '^\d+\.?\d*$'
            THEN total_deaths::NUMERIC END               AS total_deaths,
        CASE WHEN new_deaths ~ '^-?\d+\.?\d*$'
            THEN new_deaths::NUMERIC END                 AS new_deaths,
        CASE WHEN new_deaths_smoothed ~ '^-?\d+\.?\d*$'
            THEN new_deaths_smoothed::NUMERIC END        AS new_deaths_smoothed,

        -- Per-million metrics (useful for cross-country comparison)
        CASE WHEN total_cases_per_million ~ '^-?\d+\.?\d*$'
            THEN total_cases_per_million::NUMERIC END    AS total_cases_per_million,
        CASE WHEN new_cases_per_million ~ '^-?\d+\.?\d*$'
            THEN new_cases_per_million::NUMERIC END      AS new_cases_per_million,
        CASE WHEN total_deaths_per_million ~ '^-?\d+\.?\d*$'
            THEN total_deaths_per_million::NUMERIC END   AS total_deaths_per_million,

        -- Static metadata
        'covid19'                                        AS disease_id,
        'owid'                                           AS data_source

    FROM source
    WHERE
        -- Filter out aggregated rows (continents, income groups, etc.)
        -- These have country names like "World", "Europe", "High income"
        country NOT IN (
            'World', 'Europe', 'Asia', 'Africa', 'North America',
            'South America', 'Oceania', 'European Union',
            'High income', 'Upper middle income',
            'Lower middle income', 'Low income'
        )
        AND country IS NOT NULL
        AND TRIM(country) != ''
        AND date IS NOT NULL
        AND TRIM(date) != ''
)

SELECT
    c.*,
    loc.country_iso2,
    loc.country_iso3,
    loc.who_region
FROM cleaned c
LEFT JOIN {{ ref('silver_location_dim') }} loc
    ON LOWER(TRIM(c.country_name)) = LOWER(loc.country_name)