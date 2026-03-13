"""
Embedding Generator & Qdrant Upserter
=======================================
Takes chunked WHO reports, generates vector embeddings using
sentence-transformers, and stores them in Qdrant for semantic search.

What are embeddings?
  An embedding is a list of numbers (a vector) that represents
  the *meaning* of a piece of text. Texts with similar meanings
  have similar vectors. This lets us do "semantic search" —
  finding relevant text by meaning, not just keyword matching.

  Example:
    "COVID cases rising in India"  →  [0.12, -0.34, 0.78, ...]
    "Coronavirus surge in South Asia"  →  [0.11, -0.33, 0.77, ...]
    These two vectors would be very close (similar meaning!)

    "Recipe for chocolate cake"  →  [-0.89, 0.45, 0.02, ...]
    This vector would be far away (different meaning).

Model: all-MiniLM-L6-v2
  - Produces 384-dimensional vectors
  - Fast and lightweight (good for local dev)
  - Good quality for semantic similarity tasks
"""

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
)
import os
import uuid

from rag.chunker import Chunk


# ── Configuration ──
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384                  # This model outputs 384-dimensional vectors
COLLECTION_NAME = "outbreak_reports"
BATCH_SIZE = 64                      # How many texts to embed at once


def get_embedding_model() -> SentenceTransformer:
    """
    Loads the sentence-transformers model.
    First call downloads the model (~80MB); subsequent calls use cache.
    """
    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Model loaded. Output dimension: {model.get_sentence_embedding_dimension()}")
    return model


def get_qdrant_client() -> QdrantClient:
    """Creates a Qdrant client connection."""
    host = os.getenv("QDRANT_HOST", "qdrant")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    return QdrantClient(host=host, port=port)


def setup_collection(client: QdrantClient):
    """
    Creates the Qdrant collection if it doesn't exist.

    A "collection" in Qdrant is like a table in a database.
    We configure it with:
      - Vector size: 384 (matches our embedding model)
      - Distance metric: Cosine (measures angle between vectors)
      - Payload indices: for fast filtered search on metadata
    """
    collections = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME in collections:
        print(f"Collection '{COLLECTION_NAME}' already exists.")
        return

    print(f"Creating collection '{COLLECTION_NAME}'...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=EMBEDDING_DIM,
            distance=Distance.COSINE,
        ),
    )

    # Create payload indices for fast filtered search
    # This lets us do queries like "find chunks about cholera in Africa"
    for field_name, field_type in [
        ("report_id", PayloadSchemaType.KEYWORD),
        ("source", PayloadSchemaType.KEYWORD),
        ("publication_date", PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field_name,
            field_schema=field_type,
        )

    print(f"Collection '{COLLECTION_NAME}' created with indices.")


def embed_chunks(
    chunks: list[Chunk],
    model: SentenceTransformer,
) -> list[tuple[Chunk, list[float]]]:
    """
    Generates embeddings for a list of chunks.
    Returns pairs of (chunk, embedding_vector).

    We process in batches for efficiency — encoding 64 texts
    at once is much faster than encoding them one by one.
    """
    if not chunks:
        return []

    texts = [c.text for c in chunks]
    print(f"  Embedding {len(texts)} chunks in batches of {BATCH_SIZE}...")

    # encode() handles batching internally
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,  # Normalize for cosine similarity
    )

    return list(zip(chunks, embeddings.tolist()))


def upsert_to_qdrant(
    chunk_embeddings: list[tuple[Chunk, list[float]]],
    client: QdrantClient,
):
    """
    Uploads embedded chunks to Qdrant.

    Each chunk becomes a "point" in Qdrant with:
      - id: unique identifier (UUID)
      - vector: the 384-dim embedding
      - payload: metadata (report_id, title, date, etc.)

    We upsert in batches of 100 for efficiency.
    """
    if not chunk_embeddings:
        print("  No chunks to upsert.")
        return

    points = []
    for chunk, embedding in chunk_embeddings:
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                **chunk.metadata,
                "text": chunk.text,  # Store the original text for retrieval
            },
        )
        points.append(point)

    # Upsert in batches
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=batch,
        )
        print(f"  Upserted batch {i // batch_size + 1}: {len(batch)} points")

    print(f"  Total points upserted: {len(points)}")


def get_collection_stats(client: QdrantClient) -> dict:
    """Returns basic stats about the Qdrant collection."""
    info = client.get_collection(COLLECTION_NAME)
    return {
        "total_points": info.points_count,
        "vectors_count": info.vectors_count,
        "status": info.status,
    }