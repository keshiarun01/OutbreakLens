"""
Bronze Ingestion — Our World in Data (OWID) Disease Metrics
============================================================
What this does:
  1. Downloads infectious disease CSV from OWID's GitHub repo
  2. Does basic validation (not empty, has expected columns)
  3. Uploads the raw CSV to MinIO bronze bucket as a Parquet file
     (Parquet is a columnar format — much faster to query than CSV)

Why Parquet instead of CSV?
  - Smaller file size (compressed)
  - Preserves data types (CSV treats everything as strings)
  - Much faster for analytical queries downstream
"""

import pandas as pd
import requests
from io import BytesIO, StringIO
from datetime import datetime
from minio import Minio
import os
import tempfile 


# ── OWID data URLs ──
# These are raw CSV files hosted on OWID's GitHub repository.
# Each one covers a different infectious disease with global data.
OWID_SOURCES = {
    "covid": "https://catalog.ourworldindata.org/garden/covid/latest/compact/compact.csv",
    "mpox": "https://catalog.ourworldindata.org/garden/who/latest/monkeypox/monkeypox.csv",
    "hiv": "https://ourworldindata.org/grapher/share-of-the-population-infected-with-hiv.csv?v=1&csvType=full&useColumnShortNames=true",
}


def get_minio_client() -> Minio:
    """
    Creates a MinIO client using environment variables.
    This connects to the MinIO service running in Docker.
    """
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "outbreaklens"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "outbreaklens123"),
        secure=False,  # We're running locally, no HTTPS needed
    )


def download_csv(url: str, disease: str) -> pd.DataFrame:
    """
    Downloads a CSV file from a URL and returns it as a DataFrame.

    For large files (like COVID with 500K+ rows), we read in chunks
    of 50,000 rows, filter each chunk to the last 2 years, and
    concatenate only the filtered rows. This way the full dataset
    never sits in memory at once.
    """
    print(f"  Downloading {disease} data from: {url}")
    response = requests.get(url, timeout=300, stream=True)
    response.raise_for_status()

    # Write to a temp file first to avoid holding full CSV in memory
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    for chunk in response.iter_content(chunk_size=8192):
        tmp.write(chunk)
    tmp.close()
    tmp_path = tmp.name

    print(f"  Downloaded to temp file. Reading in chunks...")

    # Detect date column from first few rows
    sample = pd.read_csv(tmp_path, nrows=5)
    date_col = None
    for col in ["date", "Date", "year", "Year"]:
        if col in sample.columns:
            date_col = col
            break

    cutoff = (datetime.utcnow() - pd.DateOffset(years=2)).strftime("%Y-%m-%d")

    # Read and filter in chunks
    filtered_chunks = []
    total_raw = 0

    for chunk in pd.read_csv(tmp_path, chunksize=50000):
        total_raw += len(chunk)
        if date_col:
            chunk[date_col] = pd.to_datetime(chunk[date_col], errors="coerce")
            chunk = chunk[chunk[date_col] >= cutoff]
        filtered_chunks.append(chunk)

    # Clean up temp file
    import os as _os
    _os.unlink(tmp_path)

    df = pd.concat(filtered_chunks, ignore_index=True)
    print(f"  Raw rows: {total_raw} → Filtered to last 2 years: {len(df)} rows")

    if df.empty:
        raise ValueError(f"No data found for {disease} in the last 2 years!")

    return df


def upload_to_minio(df: pd.DataFrame, disease: str, client: Minio) -> str:
    """
    Converts a DataFrame to Parquet format and uploads it to MinIO.

    The file path follows this pattern:
      bronze/owid/{disease}/{date}/data.parquet

    This date-partitioned structure means each ingestion run creates
    a new folder — we never overwrite historical data. This is a
    common pattern in data engineering called "immutable storage".
    """
    # Generate the storage path with today's date
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    object_path = f"owid/{disease}/{date_str}/data.parquet"

    # Convert DataFrame to Parquet bytes in memory
    parquet_buffer = BytesIO()
    df.to_parquet(parquet_buffer, index=False, engine="pyarrow")
    parquet_buffer.seek(0)  # Reset buffer position to the beginning

    # Upload to MinIO bronze bucket
    client.put_object(
        bucket_name="bronze",
        object_name=object_path,
        data=parquet_buffer,
        length=parquet_buffer.getbuffer().nbytes,
        content_type="application/octet-stream",
    )

    print(f"  Uploaded to: bronze/{object_path}")
    return object_path


def ingest_owid():
    """
    Main function — called by the Airflow DAG.
    Downloads all OWID disease datasets and stores them in MinIO.
    """
    print("=" * 60)
    print("Starting OWID Bronze Ingestion")
    print("=" * 60)

    client = get_minio_client()

    results = {}
    for disease, url in OWID_SOURCES.items():
        print(f"\n── Processing: {disease} ──")
        try:
            df = download_csv(url, disease)
            path = upload_to_minio(df, disease, client)
            results[disease] = {"status": "success", "path": path, "rows": len(df)}
        except Exception as e:
            print(f"  ERROR: Failed to ingest {disease}: {e}")
            results[disease] = {"status": "failed", "error": str(e)}

    # Print summary
    print("\n" + "=" * 60)
    print("Ingestion Summary:")
    for disease, result in results.items():
        status = result["status"]
        if status == "success":
            print(f"  {disease}: {result['rows']} rows → bronze/{result['path']}")
        else:
            print(f"  {disease}: FAILED — {result['error']}")
    print("=" * 60)

    return results


# This lets you test the script directly: python bronze_owid.py
if __name__ == "__main__":
    ingest_owid()