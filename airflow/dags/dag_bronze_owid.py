
"""
Airflow DAG — Bronze OWID Ingestion
=====================================

This DAG has just one task: run the OWID ingestion script.
Later we'll add downstream tasks (validation, transformation, etc.)

Schedule: Weekly on Mondays at 6 AM UTC
  OWID updates their data periodically, so weekly is sufficient.
  The cron expression "0 6 * * 1" means:
    minute=0, hour=6, any day of month, any month, Monday(1)
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys

# ── Add ingestion folder to Python path ──
# This lets us import our ingestion scripts from the /opt/airflow/ingestion
# folder that we mounted in docker-compose.yml
sys.path.insert(0, "/opt/airflow/ingestion")

from bronze_owid import ingest_owid


# ── Default arguments for all tasks in this DAG ──
default_args = {
    "owner": "outbreaklens",            # Who owns this pipeline
    "depends_on_past": False,           # Don't wait for previous runs to succeed
    "email_on_failure": False,          # We're not setting up email alerts yet
    "email_on_retry": False,
    "retries": 2,                       # Retry failed tasks up to 2 times
    "retry_delay": timedelta(minutes=5),  # Wait 5 min between retries
}


# ── Define the DAG ──
with DAG(
    dag_id="bronze_owid_ingestion",         # Unique name shown in Airflow UI
    default_args=default_args,
    description="Ingest OWID infectious disease data into MinIO bronze layer",
    schedule="0 6 * * 1",                   # Every Monday at 6 AM UTC
    start_date=datetime(2026, 3, 1),        # DAG is eligible to run from this date
    catchup=False,                          # Don't backfill past runs on first deploy
    tags=["bronze", "ingestion", "owid"],   # Tags for filtering in the UI
) as dag:

    # ── Task: Run the ingestion ──
    # PythonOperator calls a Python function as an Airflow task.
    # When this task runs, it executes ingest_owid() which downloads
    # the CSVs and uploads them to MinIO.
    ingest_task = PythonOperator(
        task_id="ingest_owid_data",
        python_callable=ingest_owid,
    )