/*
  Silver WHO Disease Outbreak News Reports
  ─────────────────────────────────────────
  Cleans and enriches the WHO DON reports.

  Key transformations:
    1. Cast dates from text to proper timestamps
    2. Strip HTML tags from summary/overview text
    3. Build a full URL to the original WHO report
    4. Extract basic metadata (year, month) for partitioning
*/

WITH source AS (
    SELECT * FROM {{ source('bronze', 'who_don_reports') }}
),

cleaned AS (
    SELECT
        report_id,
        TRIM(title)                                         AS title,

        -- Cast date strings to proper timestamps
        CASE
            WHEN publication_date IS NOT NULL
                 AND TRIM(publication_date) != ''
            THEN publication_date::TIMESTAMP
        END                                                 AS publication_date,

        CASE
            WHEN date_modified IS NOT NULL
                 AND TRIM(date_modified) != ''
            THEN date_modified::TIMESTAMP
        END                                                 AS date_modified,

        -- Strip HTML tags from text fields using regex
        -- The bronze layer stores raw HTML; silver should be plain text
        REGEXP_REPLACE(
            COALESCE(summary, ''), '<[^>]+>', '', 'g'
        )                                                   AS summary_text,

        REGEXP_REPLACE(
            COALESCE(overview, ''), '<[^>]+>', '', 'g'
        )                                                   AS overview_text,

        -- Build full URL to the original report
        CASE
            WHEN url IS NOT NULL AND TRIM(url) != ''
            THEN 'https://www.who.int/emergencies/disease-outbreak-news/item/' || TRIM(url)
        END                                                 AS report_url,

        -- Keep raw JSON for downstream NLP parsing (Phase 2)
        raw_json,

        -- Ingestion metadata
        CASE
            WHEN ingested_at IS NOT NULL AND TRIM(ingested_at) != ''
            THEN ingested_at::TIMESTAMP
        END                                                 AS ingested_at

    FROM source
    WHERE
        report_id IS NOT NULL
        AND title IS NOT NULL
        AND TRIM(title) != ''
)

SELECT
    *,
    -- Extract date parts for easy filtering/grouping
    EXTRACT(YEAR FROM publication_date)::INTEGER   AS publication_year,
    EXTRACT(MONTH FROM publication_date)::INTEGER  AS publication_month,
    'who_don'                                      AS data_source
FROM cleaned