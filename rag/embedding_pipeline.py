"""
Embedding Pipeline
===================
End-to-end pipeline that:
  1. Reads WHO DON reports from PostgreSQL silver layer
  2. Chunks each report into meaningful pieces
  3. Generates embeddings for each chunk
  4. Upserts everything into Qdrant

This is called by an Airflow DAG to keep the vector store
in sync with new reports.
"""

import psycopg2
import psycopg2.extras
import os
import sys

# Add project root to path so we can import rag modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.chunker import chunk_report
from rag.embedder import (
    get_embedding_model,
    get_qdrant_client,
    setup_collection,
    embed_chunks,
    upsert_to_qdrant,
    get_collection_stats,
)


def get_pg_conn():
    """Creates a PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "outbreaklens"),
        user=os.getenv("POSTGRES_USER", "outbreaklens"),
        password=os.getenv("POSTGRES_PASSWORD", "outbreaklens123"),
    )


def fetch_reports() -> list[dict]:
    """
    Fetches WHO DON reports from the silver layer.
    Returns a list of dicts with the fields we need for chunking.
    """
    conn = get_pg_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute("""
        SELECT
            report_id,
            title,
            summary_text,
            overview_text,
            publication_date::TEXT AS publication_date,
            report_url
        FROM silver.silver_who_don_reports
        WHERE title IS NOT NULL
        ORDER BY publication_date DESC
    """)

    reports = cursor.fetchall()
    cursor.close()
    conn.close()

    print(f"Fetched {len(reports)} reports from silver layer")
    return [dict(r) for r in reports]


def run_embedding_pipeline():
    """
    Main pipeline function — called by Airflow DAG.
    Orchestrates the full chunk → embed → store flow.
    """
    print("=" * 60)
    print("Starting Embedding Pipeline")
    print("=" * 60)

    # Step 1: Fetch reports
    print("\n── Step 1: Fetching reports from PostgreSQL ──")
    reports = fetch_reports()
    if not reports:
        print("No reports found. Exiting.")
        return {"status": "warning", "message": "No reports to process"}

    # Step 2: Chunk all reports
    print("\n── Step 2: Chunking reports ──")
    all_chunks = []
    for report in reports:
        chunks = chunk_report(
            report_id=str(report["report_id"]),
            title=report["title"],
            summary_text=report.get("summary_text", ""),
            overview_text=report.get("overview_text", ""),
            publication_date=report.get("publication_date", ""),
            report_url=report.get("report_url", ""),
        )
        all_chunks.extend(chunks)

    print(f"  Total chunks created: {len(all_chunks)}")
    if not all_chunks:
        print("No chunks created. Exiting.")
        return {"status": "warning", "message": "No chunks generated"}

    # Show a sample chunk
    print(f"\n  Sample chunk (first 200 chars):")
    print(f"  '{all_chunks[0].text[:200]}...'")
    print(f"  Metadata: {all_chunks[0].metadata}")

    # Step 3: Generate embeddings
    print("\n── Step 3: Generating embeddings ──")
    model = get_embedding_model()
    chunk_embeddings = embed_chunks(all_chunks, model)
    print(f"  Generated {len(chunk_embeddings)} embeddings")

    # Step 4: Setup Qdrant collection and upsert
    print("\n── Step 4: Upserting to Qdrant ──")
    qdrant_client = get_qdrant_client()
    setup_collection(qdrant_client)
    upsert_to_qdrant(chunk_embeddings, qdrant_client)

    # Step 5: Print stats
    print("\n── Step 5: Collection Stats ──")
    stats = get_collection_stats(qdrant_client)
    print(f"  Total points in collection: {stats['total_points']}")
    print(f"  Collection status: {stats['status']}")

    print("\n" + "=" * 60)
    print("Embedding Pipeline Complete!")
    print(f"  Reports processed: {len(reports)}")
    print(f"  Chunks created: {len(all_chunks)}")
    print(f"  Vectors stored: {stats['total_points']}")
    print("=" * 60)

    return {
        "status": "success",
        "reports_processed": len(reports),
        "chunks_created": len(all_chunks),
        "vectors_stored": stats["total_points"],
    }


if __name__ == "__main__":
    run_embedding_pipeline()