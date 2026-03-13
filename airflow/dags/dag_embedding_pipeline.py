
"""
Airflow DAG — Embedding Pipeline
==================================
Reads WHO DON reports from the silver layer, chunks them,
generates embeddings, and stores them in Qdrant.

Schedule: Daily at 9 AM UTC (after bronze→silver pipeline completes)

IMPORTANT: We do NOT import heavy libraries (sentence-transformers,
qdrant-client) at the top level. Airflow parses every DAG file on
a 30-second timeout, and importing ML libraries takes too long.
Instead, we import inside the task function — this is a common
Airflow best practice called "lazy imports".
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta


def _run_embedding_pipeline():
    """
    Wrapper that does the heavy imports only at execution time,
    not at DAG parse time. This avoids the 30s import timeout.
    """
    import sys
    sys.path.insert(0, "/opt/airflow")
    from rag.embedding_pipeline import run_embedding_pipeline
    return run_embedding_pipeline()


default_args = {
    "owner": "outbreaklens",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}


with DAG(
    dag_id="embedding_pipeline",
    default_args=default_args,
    description="Chunk WHO reports, generate embeddings, store in Qdrant",
    schedule="0 9 * * *",
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["phase2", "embeddings", "qdrant", "rag"],
) as dag:

    embed_task = PythonOperator(
        task_id="run_embedding_pipeline",
        python_callable=_run_embedding_pipeline,
    )