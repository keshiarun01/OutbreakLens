
"""
Bronze Loader — MinIO Parquet → PostgreSQL Bronze Schema
==========================================================
What this does:
  1. Reads the latest Parquet files from each MinIO bronze folder
  2. Loads them into PostgreSQL tables in the 'bronze' schema
  3. This makes the data queryable by dbt and Soda

Why this extra step?
  - MinIO (data lake) = cheap storage for raw files, great for archival
  - PostgreSQL (warehouse) = fast SQL queries, needed by dbt and Soda
  - This pattern (lake → warehouse) is used in every modern data stack

Tables created:
  - bronze.owid_covid
  - bronze.owid_mpox
  - bronze.owid_hiv
  - bronze.who_don_reports
  - bronze.geonames_countries
"""

import pandas as pd
from io import BytesIO, StringIO
from minio import Minio
import psycopg2
import os


def get_minio_client() -> Minio:
    """Creates a MinIO client."""
    return Minio(
        endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ROOT_USER", "outbreaklens"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "outbreaklens123"),
        secure=False,
    )


def get_pg_conn():
    """Creates a raw psycopg2 connection to PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "outbreaklens"),
        user=os.getenv("POSTGRES_USER", "outbreaklens"),
        password=os.getenv("POSTGRES_PASSWORD", "outbreaklens123"),
    )


def find_latest_object(client: Minio, bucket: str, prefix: str) -> str | None:
    """
    Finds the most recent parquet file in a MinIO prefix (folder).
    Since dates sort alphabetically, the last one is the newest.
    """
    objects = list(client.list_objects(bucket, prefix=prefix, recursive=True))
    parquet_objects = [obj for obj in objects if obj.object_name.endswith(".parquet")]

    if not parquet_objects:
        print(f"  WARNING: No parquet files found in {bucket}/{prefix}")
        return None

    latest = sorted(parquet_objects, key=lambda x: x.object_name)[-1]
    print(f"  Latest file: {latest.object_name}")
    return latest.object_name


def read_parquet_from_minio(client: Minio, bucket: str, object_name: str) -> pd.DataFrame:
    """Downloads a Parquet file from MinIO and reads it into a DataFrame."""
    response = client.get_object(bucket, object_name)
    data = BytesIO(response.read())
    response.close()
    response.release_conn()

    df = pd.read_parquet(data)
    print(f"  Read {len(df)} rows, {len(df.columns)} columns")
    return df


def load_to_postgres(df: pd.DataFrame, table_name: str, conn):
    """
    Loads a DataFrame into PostgreSQL using raw psycopg2.

    Key design decision: ALL bronze columns are stored as TEXT.
    This is intentional and is best practice because:
      - Bronze layer should store raw data exactly as received
      - No type casting errors from NULLs or unexpected formats
      - Type conversion happens in the silver layer via dbt
      - This matches the philosophy: "store first, clean later"

    For large datasets, we load in chunks of 50,000 rows.
    """
    cursor = conn.cursor()
    full_table = f"bronze.{table_name}"

    # Step 1: Drop old table
    cursor.execute(f"DROP TABLE IF EXISTS {full_table}")

    # Step 2: Create table — ALL columns as TEXT (bronze = raw)
    columns = []
    for col_name in df.columns:
        safe_name = col_name.replace(" ", "_").replace("-", "_").lower()
        columns.append(f'"{safe_name}" TEXT')

    create_sql = f"CREATE TABLE {full_table} ({', '.join(columns)})"
    cursor.execute(create_sql)
    conn.commit()

    # Step 3: Convert all data to strings, replacing NaN/NaT with None
    # This ensures PostgreSQL receives proper NULLs instead of ""
    df_str = df.astype(str).replace({"nan": None, "NaT": None, "None": None, "": None})

    # Step 4: Bulk load in chunks
    chunk_size = 50000
    total_rows = len(df_str)
    loaded = 0

    for start in range(0, total_rows, chunk_size):
        chunk = df_str.iloc[start:start + chunk_size]

        buffer = StringIO()
        chunk.to_csv(buffer, index=False, header=False, sep="\t", na_rep="\\N")
        buffer.seek(0)

        cursor.copy_expert(
            f"COPY {full_table} FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')",
            buffer,
        )
        conn.commit()

        loaded += len(chunk)
        print(f"    Loaded chunk: {loaded}/{total_rows} rows")

        del buffer
        del chunk

    del df_str
    cursor.close()
    print(f"  Loaded {total_rows} rows into {full_table}")


def load_all_bronze():
    """
    Main function — loads all bronze Parquet files from MinIO
    into PostgreSQL bronze schema tables.
    """
    print("=" * 60)
    print("Loading Bronze Layer: MinIO → PostgreSQL")
    print("=" * 60)

    client = get_minio_client()
    conn = get_pg_conn()

    # Ensure the bronze schema exists
    cursor = conn.cursor()
    cursor.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    conn.commit()
    cursor.close()

    # ── Define what to load ──
    load_map = [
        ("owid/covid/", "owid_covid"),
        ("owid/mpox/", "owid_mpox"),
        ("owid/hiv/", "owid_hiv"),
        ("who_don/", "who_don_reports"),
        ("geonames/", "geonames_countries"),
    ]

    results = {}
    for prefix, table_name in load_map:
        print(f"\n── Loading: {prefix} → bronze.{table_name} ──")
        try:
            object_name = find_latest_object(client, "bronze", prefix)
            if not object_name:
                results[table_name] = "skipped (no file found)"
                continue

            df = read_parquet_from_minio(client, "bronze", object_name)
            load_to_postgres(df, table_name, conn)
            results[table_name] = f"success ({len(df)} rows)"

        except Exception as e:
            print(f"  ERROR: {e}")
            conn.rollback()  # Reset the connection after an error
            results[table_name] = f"failed: {e}"

    conn.close()

    # Print summary
    print("\n" + "=" * 60)
    print("Load Summary:")
    for table, status in results.items():
        print(f"  bronze.{table}: {status}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    load_all_bronze()