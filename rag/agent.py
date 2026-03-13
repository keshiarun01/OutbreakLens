
"""
RAG Agent — OutbreakLens Query Engine
======================================
This is the brain of the system. It takes a user's question and:

1. ROUTES it to the right chain based on the question type:
   - VECTOR: qualitative questions about outbreak details, narratives
   - SQL: quantitative questions about trends, counts, comparisons
   - HYBRID: complex questions needing both data types

2. RETRIEVES relevant context:
   - Vector chain: searches Qdrant for semantically similar report chunks
   - SQL chain: generates and executes SQL against gold layer tables

3. GENERATES a response using GPT with the retrieved context

Example questions:
  VECTOR: "What is WHO's recommendation for mpox prevention?"
  SQL:    "How many COVID cases were reported in India last month?"
  HYBRID: "Which countries have accelerating outbreaks and what measures are recommended?"
"""

import os
import psycopg2
import psycopg2.extras
from openai import OpenAI
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer


# ── Configuration ──
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "outbreak_reports"
GPT_MODEL = "gpt-4o-mini"  # Cost-effective and fast


def get_openai_client() -> OpenAI:
    """Creates an OpenAI client using the API key from environment."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set!")
    return OpenAI(api_key=api_key)


def get_qdrant_client() -> QdrantClient:
    """Creates a Qdrant client."""
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    return QdrantClient(host=host, port=port)


def get_pg_conn():
    """Creates a PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "outbreaklens"),
        user=os.getenv("POSTGRES_USER", "outbreaklens"),
        password=os.getenv("POSTGRES_PASSWORD", "outbreaklens123"),
    )


# ─────────────────────────────────────────────────
# 1. ROUTER — Classifies the question type
# ─────────────────────────────────────────────────

ROUTER_PROMPT = """You are a query router for a disease outbreak intelligence system.
Classify the user's question into exactly one category:

- VECTOR: Questions about outbreak details, WHO recommendations, disease descriptions,
  response measures, risk assessments, or any qualitative/narrative information.
  Examples: "What are symptoms of Nipah?", "What did WHO recommend for cholera?"

- SQL: Questions about numbers, counts, trends, comparisons, rankings, or any
  quantitative data. These can be answered with database queries.
  Examples: "How many COVID cases in India?", "Which country has the most mpox deaths?"

- HYBRID: Complex questions that need both narrative context AND quantitative data.
  Examples: "Which countries have rising outbreaks and what measures are being taken?"

Respond with ONLY one word: VECTOR, SQL, or HYBRID"""


def route_query(question: str, openai_client: OpenAI) -> str:
    """
    Uses GPT to classify a question into VECTOR, SQL, or HYBRID.
    This determines which retrieval chain to use.
    """
    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": question},
        ],
        max_tokens=10,
        temperature=0,  # Deterministic — same question always gets same route
    )
    route = response.choices[0].message.content.strip().upper()

    # Validate the response
    if route not in ("VECTOR", "SQL", "HYBRID"):
        route = "HYBRID"  # Default to hybrid if unclear

    return route


# ─────────────────────────────────────────────────
# 2. VECTOR CHAIN — Semantic search over WHO reports
# ─────────────────────────────────────────────────

def vector_search(
    question: str,
    qdrant_client: QdrantClient,
    embedding_model: SentenceTransformer,
    top_k: int = 5,
) -> list[dict]:
    """
    Searches Qdrant for the most relevant report chunks.

    How it works:
      1. Convert the question into a 384-dim vector (same model used for indexing)
      2. Find the top-k closest vectors in Qdrant (cosine similarity)
      3. Return the matching chunks with their text and metadata
    """
    from qdrant_client.models import models

    # Embed the question
    query_vector = embedding_model.encode(question, normalize_embeddings=True).tolist()

    # Search Qdrant (compatible with both old and new client versions)
    try:
        # New API (qdrant-client >= 1.12)
        results = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
        ).points
    except (AttributeError, TypeError):
        # Old API (qdrant-client < 1.12)
        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
        )

    # Format results
    chunks = []
    for result in results:
        payload = result.payload or {}
        chunks.append({
            "text": payload.get("text", ""),
            "title": payload.get("title", ""),
            "publication_date": payload.get("publication_date", ""),
            "report_url": payload.get("report_url", ""),
            "score": result.score,
        })

    return chunks


# ─────────────────────────────────────────────────
# 3. SQL CHAIN — Generate and execute SQL queries
# ─────────────────────────────────────────────────

GOLD_SCHEMA_DESCRIPTION = """
Available tables in the PostgreSQL database:

1. gold.gold_active_outbreaks
   - country_name, country_iso2, country_iso3, who_region
   - disease_id ('covid19' or 'mpox')
   - latest_report_date, latest_total_cases, latest_total_deaths
   - avg_cases_curr_week, avg_cases_prev_week
   - trend_direction ('accelerating', 'decelerating', 'stable', 'unknown')
   - days_since_last_report, data_source

2. gold.gold_disease_trend_weekly
   - disease_id, who_region, week_start
   - weekly_cases, weekly_deaths, days_with_data
   - rolling_avg_cases_4w, rolling_avg_deaths_4w
   - prev_week_cases, wow_growth_pct

3. gold.gold_outbreak_timeline
   - report_id, title, publication_date, publication_year, publication_month
   - summary_text, overview_text, report_url
   - report_sequence, days_since_prev_report
   - cumulative_report_count, reports_in_same_month

4. gold.gold_alert_signals
   - disease_id, who_region, week_start
   - alert_type ('SURGE', 'RAPID_GROWTH', 'HIGH_MORTALITY')
   - alert_description, weekly_cases, rolling_avg_cases_4w
   - severity ('critical', 'high', 'medium'), severity_rank

5. silver.disease_dim
   - disease_id, disease_name, transmission_type, typical_cfr_pct, icd11_code
"""

SQL_GENERATION_PROMPT = f"""You are a SQL expert for a disease outbreak database.
Generate a PostgreSQL query to answer the user's question.

{GOLD_SCHEMA_DESCRIPTION}

Rules:
- Write ONLY the SQL query, nothing else
- Use proper PostgreSQL syntax
- Always include LIMIT to prevent huge result sets
- Use the gold schema tables when possible
- Do NOT use DELETE, UPDATE, INSERT, DROP, or any DDL statements
- Only use SELECT statements
"""


def generate_and_execute_sql(question: str, openai_client: OpenAI) -> dict:
    """
    Uses GPT to generate a SQL query, then executes it safely.

    Safety measures:
      - Only SELECT statements are allowed
      - Results are limited to 50 rows
      - Query runs with a read-only intent
    """
    # Generate SQL
    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": SQL_GENERATION_PROMPT},
            {"role": "user", "content": question},
        ],
        max_tokens=500,
        temperature=0,
    )
    sql_query = response.choices[0].message.content.strip()

    # Clean up: remove markdown code fences if present
    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

    # Safety check: only allow SELECT
    if not sql_query.upper().startswith("SELECT"):
        return {
            "sql": sql_query,
            "error": "Only SELECT queries are allowed",
            "results": [],
        }

    # Execute the query
    try:
        conn = get_pg_conn()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        cursor.close()
        conn.close()

        # Convert to list of dicts
        results = [dict(row) for row in rows]

        return {
            "sql": sql_query,
            "columns": columns,
            "results": results[:50],  # Safety limit
            "row_count": len(results),
        }
    except Exception as e:
        return {
            "sql": sql_query,
            "error": str(e),
            "results": [],
        }


# ─────────────────────────────────────────────────
# 4. RESPONSE GENERATOR — Final answer with sources
# ─────────────────────────────────────────────────

RESPONSE_PROMPT = """You are an outbreak intelligence analyst for the OutbreakLens platform.
Answer the user's question based ONLY on the provided context.

Rules:
- Be concise but thorough
- Cite specific sources when possible (report titles, dates, URLs)
- If the context doesn't contain enough information, say so honestly
- Include relevant numbers and statistics when available
- Format your response clearly with paragraphs
"""


def generate_response(
    question: str,
    context: str,
    openai_client: OpenAI,
    route: str,
) -> str:
    """
    Generates the final response using GPT with retrieved context.
    """
    system_msg = RESPONSE_PROMPT + f"\n\nQuery type: {route}"

    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        max_tokens=1000,
        temperature=0.3,  # Slightly creative but mostly factual
    )

    return response.choices[0].message.content


# ─────────────────────────────────────────────────
# 5. MAIN AGENT — Ties everything together
# ─────────────────────────────────────────────────

class OutbreakLensAgent:
    """
    The main RAG agent that orchestrates routing, retrieval,
    and response generation.

    Usage:
        agent = OutbreakLensAgent()
        result = agent.query("What is the current mpox situation?")
        print(result["answer"])
    """

    def __init__(self):
        print("Initializing OutbreakLens Agent...")
        self.openai_client = get_openai_client()
        self.qdrant_client = get_qdrant_client()
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        print("Agent ready.")

    def query(self, question: str) -> dict:
        """
        Process a user question end-to-end.

        Returns a dict with:
          - answer: the generated response text
          - route: which chain was used (VECTOR/SQL/HYBRID)
          - sources: retrieved context details
        """
        print(f"\n{'─' * 50}")
        print(f"Question: {question}")

        # Step 1: Route
        route = route_query(question, self.openai_client)
        print(f"Route: {route}")

        context_parts = []
        sources = {}

        # Step 2: Retrieve context based on route
        if route in ("VECTOR", "HYBRID"):
            chunks = vector_search(
                question, self.qdrant_client, self.embedding_model
            )
            if chunks:
                vector_context = "\n\n".join([
                    f"[Source: {c['title']} ({c['publication_date']})] {c['text']}"
                    for c in chunks
                ])
                context_parts.append(f"WHO Report Excerpts:\n{vector_context}")
                sources["vector_results"] = chunks
                print(f"Vector search: {len(chunks)} chunks retrieved")

        if route in ("SQL", "HYBRID"):
            sql_result = generate_and_execute_sql(question, self.openai_client)
            if sql_result.get("results"):
                # Format SQL results as readable text
                sql_context = f"SQL Query: {sql_result['sql']}\n\n"
                sql_context += f"Results ({sql_result['row_count']} rows):\n"
                for row in sql_result["results"][:20]:
                    sql_context += str(row) + "\n"
                context_parts.append(f"Database Query Results:\n{sql_context}")
                sources["sql_result"] = sql_result
                print(f"SQL chain: {sql_result['row_count']} rows returned")
            elif sql_result.get("error"):
                print(f"SQL error: {sql_result['error']}")
                sources["sql_result"] = sql_result

        # Step 3: Generate response
        if not context_parts:
            context = "No relevant information was found in the database."
        else:
            context = "\n\n---\n\n".join(context_parts)

        answer = generate_response(question, context, self.openai_client, route)
        print(f"Response generated ({len(answer)} chars)")

        return {
            "answer": answer,
            "route": route,
            "sources": sources,
        }