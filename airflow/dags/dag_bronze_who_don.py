
"""
Airflow DAG — Bronze WHO Disease Outbreak News Ingestion
=========================================================
Fetches outbreak reports from WHO's public API and stores
them as Parquet files in MinIO's bronze bucket.

Schedule: Daily at 7 AM UTC
  WHO publishes new DON reports several times per week,
  so daily checks ensure we catch new reports promptly.
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys

sys.path.insert(0, "/opt/airflow/ingestion")

from bronze_who_don import ingest_who_don


default_args = {
    "owner": "outbreaklens",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="bronze_who_don_ingestion",
    default_args=default_args,
    description="Ingest WHO Disease Outbreak News into MinIO bronze layer",
    schedule="0 7 * * *",                   # Daily at 7 AM UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["bronze", "ingestion", "who"],
) as dag:

    ingest_task = PythonOperator(
        task_id="ingest_who_don_reports",
        python_callable=ingest_who_don,
    )