
"""
Bronze Ingestion — WHO Disease Outbreak News (DON)
====================================================
What this does:
  1. Calls the WHO public REST API to fetch outbreak reports
  2. Paginates through all available reports (API returns batches)
  3. Stores raw JSON data as Parquet in MinIO bronze bucket

The WHO DON API:
  - Base URL: https://www.who.int/api/news/diseaseoutbreaknews
  - Returns JSON with OData-style pagination ($top, $skip)
  - Each report has: title, summary, publication date, URL, etc.
  - No authentication required (public API)

Why store raw JSON as Parquet?
  - We keep the FULL raw response (nothing lost)
  - Parquet compresses well and preserves types
  - In the silver layer, we'll parse and extract structured fields
"""

import pandas as pd
import requests
import time
from io import BytesIO
from datetime import datetime
from minio import Minio
import os
import json


# ── WHO API Configuration ──
WHO_DON_BASE_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
PAGE_SIZE = 50  # Number of reports per API call (max varies, 50 is safe)


def get_minio_client() -> Minio:
    """Creates a MinIO client using environment variables."""
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "outbreaklens"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "outbreaklens123"),
        secure=False,
    )


def fetch_don_reports(max_reports: int = 500) -> list[dict]:
    """
    Fetches WHO Disease Outbreak News reports via their REST API.

    The API uses OData-style pagination:
      - $top = how many records to return per request
      - $skip = how many records to skip (for pagination)
      - $orderby = sort order

    We loop until we've fetched all available reports or hit max_reports.

    Parameters:
        max_reports: Maximum number of reports to fetch (safety limit)

    Returns:
        List of report dictionaries with raw API data
    """
    all_reports = []
    skip = 0

    print(f"Fetching WHO DON reports (max: {max_reports})...")

    while len(all_reports) < max_reports:
        # Build the API URL with pagination parameters
        url = (
            f"{WHO_DON_BASE_URL}"
            f"?$top={PAGE_SIZE}"
            f"&$skip={skip}"
            f"&$orderby=PublicationDate desc"
        )

        print(f"  Requesting: skip={skip}, top={PAGE_SIZE}...")
        response = requests.get(url, timeout=60)
        response.raise_for_status()

        data = response.json()
        reports = data.get("value", [])

        # If no more reports returned, we've reached the end
        if not reports:
            print(f"  No more reports. Total fetched: {len(all_reports)}")
            break

        all_reports.extend(reports)
        skip += PAGE_SIZE

        print(f"  Got {len(reports)} reports. Running total: {len(all_reports)}")

        # Be polite to the WHO API — wait 1 second between requests
        time.sleep(1)

    # Trim to max_reports if we went over
    all_reports = all_reports[:max_reports]
    print(f"  Final count: {len(all_reports)} reports")

    return all_reports


def safe_get_text(field) -> str:
    """
    Safely extracts text from a WHO API field.
    The API is inconsistent — some fields are plain strings,
    others are dicts like {"Value": "..."}, and some are None.
    This helper handles all cases.
    """
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("Value", "") or ""
    return str(field)


def transform_to_dataframe(reports: list[dict]) -> pd.DataFrame:
    """
    Converts raw API response into a clean DataFrame.

    We extract the most useful fields while also preserving
    the full raw JSON for each report (so nothing is lost).
    """
    rows = []
    for report in reports:
        row = {
            # ── Core fields ──
            "report_id": report.get("Id"),
            "title": safe_get_text(report.get("Title")),
            "publication_date": report.get("PublicationDate"),
            "url": report.get("UrlName", ""),

            # ── Content fields (HTML text from the API) ──
            "summary": safe_get_text(report.get("Summary")),
            "overview": safe_get_text(report.get("Overview")),

            # ── Metadata ──
            "date_modified": report.get("DateModified"),

            # ── Full raw JSON (preserved for silver layer parsing) ──
            "raw_json": json.dumps(report),

            # ── Ingestion metadata ──
            "ingested_at": datetime.utcnow().isoformat(),
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # Convert date columns
    for col in ["publication_date", "date_modified"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


def upload_to_minio(df: pd.DataFrame, client: Minio) -> str:
    """Uploads the DataFrame as Parquet to MinIO bronze bucket."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    object_path = f"who_don/{date_str}/reports.parquet"

    parquet_buffer = BytesIO()
    df.to_parquet(parquet_buffer, index=False, engine="pyarrow")
    parquet_buffer.seek(0)

    client.put_object(
        bucket_name="bronze",
        object_name=object_path,
        data=parquet_buffer,
        length=parquet_buffer.getbuffer().nbytes,
        content_type="application/octet-stream",
    )

    print(f"  Uploaded to: bronze/{object_path}")
    return object_path


def ingest_who_don():
    """
    Main function — called by the Airflow DAG.
    Fetches WHO DON reports and stores them in MinIO bronze layer.
    """
    print("=" * 60)
    print("Starting WHO Disease Outbreak News Bronze Ingestion")
    print("=" * 60)

    # Step 1: Fetch reports from WHO API
    reports = fetch_don_reports(max_reports=500)

    if not reports:
        print("WARNING: No reports fetched from WHO API!")
        return {"status": "warning", "message": "No reports fetched"}

    # Step 2: Transform to DataFrame
    print("\nTransforming to DataFrame...")
    df = transform_to_dataframe(reports)
    print(f"  DataFrame shape: {df.shape}")
    print(f"  Date range: {df['publication_date'].min()} to {df['publication_date'].max()}")

    # Step 3: Upload to MinIO
    print("\nUploading to MinIO...")
    client = get_minio_client()
    path = upload_to_minio(df, client)

    print("\n" + "=" * 60)
    print(f"WHO DON Ingestion Complete!")
    print(f"  Reports: {len(df)}")
    print(f"  Stored at: bronze/{path}")
    print("=" * 60)

    return {"status": "success", "path": path, "report_count": len(df)}


if __name__ == "__main__":
    ingest_who_don()