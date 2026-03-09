
"""
Airflow DAG — Load Bronze Parquet Files into PostgreSQL
=========================================================
Reads the latest Parquet files from MinIO and loads them
into PostgreSQL bronze schema tables so dbt and Soda can query them.

Schedule: Daily at 8 AM UTC (after ingestion DAGs finish)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys

sys.path.insert(0, "/opt/airflow/ingestion")

from bronze_to_postgres import load_all_bronze


default_args = {
    "owner": "outbreaklens",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


with DAG(
    dag_id="bronze_load_to_postgres",
    default_args=default_args,
    description="Load bronze Parquet files from MinIO into PostgreSQL",
    schedule="0 8 * * *",                   # Daily at 8 AM UTC
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["bronze", "loader", "postgres"],
) as dag:

    load_task = PythonOperator(
        task_id="load_bronze_to_postgres",
        python_callable=load_all_bronze,
    )