
"""
Bronze Ingestion — GeoNames Country Reference Data
=====================================================
What this does:
  1. Downloads the GeoNames "countryInfo" dataset (free, no API key needed)
  2. This gives us every country with:
     - ISO country codes (2-letter and 3-letter)
     - Country name, capital, population, area
     - Continent code
     - Latitude/longitude of the country centroid
  3. Stores as Parquet in MinIO bronze bucket

This is a REFERENCE dataset — it rarely changes, so we only
need to run this once (or monthly to pick up any updates).

GeoNames is a free geographical database available under
a Creative Commons license.
"""

import pandas as pd
import requests
from io import BytesIO, StringIO
from datetime import datetime
from minio import Minio
import os


# GeoNames provides a tab-separated file with country info
GEONAMES_COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"


def get_minio_client() -> Minio:
    """Creates a MinIO client using environment variables."""
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "outbreaklens"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "outbreaklens123"),
        secure=False,
    )


def download_geonames() -> pd.DataFrame:
    """
    Downloads and parses the GeoNames countryInfo.txt file.

    The file is tab-separated with comment lines starting with '#'.
    We skip those comments and parse the actual data.
    """
    print("Downloading GeoNames country data...")
    response = requests.get(GEONAMES_COUNTRY_URL, timeout=60)
    response.raise_for_status()

    # Filter out comment lines (start with #)
    lines = response.text.split("\n")
    header_line = None
    data_lines = []

    for line in lines:
        if line.startswith("#ISO\t") or line.startswith("#ISO "):
            # This is the header row (starts with #ISO)
            header_line = line.lstrip("#").strip()
        elif not line.startswith("#") and line.strip():
            data_lines.append(line)

    if not header_line:
        # Fallback column names if header not found
        columns = [
            "iso2", "iso3", "iso_numeric", "fips", "country_name",
            "capital", "area_sq_km", "population", "continent",
            "tld", "currency_code", "currency_name", "phone",
            "postal_code_format", "postal_code_regex",
            "languages", "geoname_id", "neighbours",
            "equivalent_fips_code"
        ]
    else:
        columns = header_line.split("\t")

    # Parse the data
    data_text = "\n".join(data_lines)
    df = pd.read_csv(
        StringIO(data_text),
        sep="\t",
        header=None,
        names=columns,
        keep_default_na=False,
    )

    print(f"  Parsed {len(df)} countries")
    print(f"  Columns: {list(df.columns)}")

    return df


def upload_to_minio(df: pd.DataFrame, client: Minio) -> str:
    """Uploads the DataFrame as Parquet to MinIO bronze bucket."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    object_path = f"geonames/{date_str}/countries.parquet"

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


def ingest_geonames():
    """
    Main function — called by the Airflow DAG.
    Downloads GeoNames country reference data and stores in MinIO.
    """
    print("=" * 60)
    print("Starting GeoNames Bronze Ingestion")
    print("=" * 60)

    # Step 1: Download
    df = download_geonames()

    # Step 2: Upload
    print("\nUploading to MinIO...")
    client = get_minio_client()
    path = upload_to_minio(df, client)

    print("\n" + "=" * 60)
    print(f"GeoNames Ingestion Complete!")
    print(f"  Countries: {len(df)}")
    print(f"  Stored at: bronze/{path}")
    print("=" * 60)

    return {"status": "success", "path": path, "country_count": len(df)}


if __name__ == "__main__":
    ingest_geonames()