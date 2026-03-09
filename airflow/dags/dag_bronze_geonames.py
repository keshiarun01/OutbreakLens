
"""
Airflow DAG — Bronze GeoNames Country Reference Data
======================================================
Downloads country reference data (ISO codes, coordinates,
population) from GeoNames.

Schedule: Monthly on the 1st at 5 AM UTC
  This is reference data that rarely changes.
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys

sys.path.insert(0, "/opt/airflow/ingestion")

from bronze_geonames import ingest_geonames


default_args = {
    "owner": "outbreaklens",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="bronze_geonames_ingestion",
    default_args=default_args,
    description="Ingest GeoNames country reference data into MinIO bronze layer",
    schedule="0 5 1 * *",                   # 1st of every month at 5 AM UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["bronze", "ingestion", "geonames", "reference"],
) as dag:

    ingest_task = PythonOperator(
        task_id="ingest_geonames_countries",
        python_callable=ingest_geonames,
    )