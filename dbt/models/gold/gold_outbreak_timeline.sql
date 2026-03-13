
/*
  Gold: Outbreak Timeline
  ───────────────────────
  Creates a timeline view of WHO Disease Outbreak News reports.
  Each row is a report, enriched with sequencing info like
  report number, days since first report, etc.

  This helps track how outbreaks evolve over time.
*/

WITH reports AS (
    SELECT
        report_id,
        title,
        publication_date,
        publication_year,
        publication_month,
        summary_text,
        overview_text,
        report_url,
        data_source
    FROM {{ ref('silver_who_don_reports') }}
    WHERE publication_date IS NOT NULL
)

SELECT
    *,

    -- Sequence number (1 = oldest report, N = newest)
    ROW_NUMBER() OVER (ORDER BY publication_date ASC)    AS report_sequence,

    -- Days since the previous report was published
    publication_date - LAG(publication_date) OVER (
        ORDER BY publication_date
    )                                                    AS days_since_prev_report,

    -- Running total of reports
    COUNT(*) OVER (
        ORDER BY publication_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                    AS cumulative_report_count,

    -- Reports per month (for volume tracking)
    COUNT(*) OVER (
        PARTITION BY publication_year, publication_month
    )                                                    AS reports_in_same_month

FROM reports