
/*
  Silver Location Dimension
  ─────────────────────────
  Cleans and enriches the GeoNames country data into a proper
  dimension table. A "dimension" in data warehousing is a
  reference table with descriptive attributes — in this case,
  everything about a country: its codes, name, region, etc.

  Key transformations:
    1. Cast text columns to proper types (population → integer)
    2. Add WHO region classification based on continent
    3. Filter out invalid/empty rows
    4. Standardize column names
*/

WITH source AS (
    SELECT * FROM {{ source('bronze', 'geonames_countries') }}
),

cleaned AS (
    SELECT
        -- ISO country codes (the universal way to identify countries)
        UPPER(TRIM(iso))              AS country_iso2,    -- 2-letter code: US, GB, IN
        UPPER(TRIM(iso3))             AS country_iso3,    -- 3-letter code: USA, GBR, IND
        TRIM(country)                 AS country_name,
        TRIM(capital)                 AS capital,
        TRIM(continent)               AS continent_code,

        -- Numeric fields: cast from TEXT (bronze stores everything as text)
        CASE
            WHEN population ~ '^\d+$' THEN population::BIGINT
            ELSE NULL
        END AS population,

        -- Map continent codes to readable names
        CASE TRIM(continent)
            WHEN 'AF' THEN 'Africa'
            WHEN 'AS' THEN 'Asia'
            WHEN 'EU' THEN 'Europe'
            WHEN 'NA' THEN 'North America'
            WHEN 'SA' THEN 'South America'
            WHEN 'OC' THEN 'Oceania'
            WHEN 'AN' THEN 'Antarctica'
            ELSE 'Unknown'
        END AS continent_name,

        -- WHO Region mapping (approximate, based on continent)
        -- WHO regions don't perfectly align with continents,
        -- but this is a good starting approximation.
        CASE TRIM(continent)
            WHEN 'AF' THEN 'AFRO'       -- African Region
            WHEN 'EU' THEN 'EURO'       -- European Region
            WHEN 'NA' THEN 'AMRO'       -- Region of the Americas
            WHEN 'SA' THEN 'AMRO'       -- Region of the Americas
            WHEN 'OC' THEN 'WPRO'       -- Western Pacific Region
            WHEN 'AS' THEN 'SEARO'      -- South-East Asia (default for Asia)
            ELSE 'Unknown'
        END AS who_region

    FROM source
    WHERE
        iso IS NOT NULL
        AND TRIM(iso) != ''
        AND country IS NOT NULL
        AND TRIM(country) != ''
)

SELECT * FROM cleaned