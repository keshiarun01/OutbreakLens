
"""
OutbreakLens — Streamlit Frontend
===================================
A chat-based interface for querying the OutbreakLens
disease outbreak intelligence platform.

Run with:
    cd ~/outbreaklens
    streamlit run streamlit/app.py
"""

import streamlit as st
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set environment defaults for local development
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("POSTGRES_HOST", "localhost")


# ── Page Configuration ──
st.set_page_config(
    page_title="OutbreakLens",
    page_icon="🦠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Initialize the Agent (cached so it loads only once) ──
@st.cache_resource
def load_agent():
    """Load the RAG agent once and reuse across reruns."""
    from rag.agent import OutbreakLensAgent
    return OutbreakLensAgent()


# ── Sidebar ──
with st.sidebar:
    st.title("🦠 OutbreakLens")
    st.markdown("**Disease Outbreak Intelligence Platform**")
    st.divider()

    st.markdown("### How it works")
    st.markdown("""
    Ask questions about global disease outbreaks. The system
    automatically routes your question to the right data source:

    🔍 **Vector Search** — WHO report details, recommendations, narratives

    📊 **SQL Query** — Case counts, trends, comparisons, rankings

    🔀 **Hybrid** — Complex questions needing both
    """)

    st.divider()

    st.markdown("### Example Questions")
    example_questions = [
        "What is the current mpox situation globally?",
        "Which countries have the most COVID deaths?",
        "What are the active outbreak alerts this week?",
        "What did WHO recommend for cholera prevention?",
        "Show me the weekly trend of mpox cases",
        "Which diseases have critical alert signals?",
    ]
    for q in example_questions:
        if st.button(q, key=q, use_container_width=True):
            st.session_state["preset_question"] = q

    st.divider()
    st.markdown("### Data Sources")
    st.markdown("""
    - 🌐 WHO Disease Outbreak News (500 reports)
    - 📊 Our World in Data (COVID-19, Mpox)
    - 🗺️ GeoNames (252 countries)
    """)

    st.divider()
    st.caption("Built with Airflow • dbt • Qdrant • GPT-4o-mini")


# ── Main Chat Interface ──
st.title("🦠 OutbreakLens")
st.caption("Ask questions about global disease outbreaks — powered by RAG")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # Show metadata for assistant messages
        if message["role"] == "assistant" and "metadata" in message:
            meta = message["metadata"]
            cols = st.columns(3)
            with cols[0]:
                route_emoji = {"VECTOR": "🔍", "SQL": "📊", "HYBRID": "🔀"}
                st.caption(f"{route_emoji.get(meta['route'], '❓')} Route: {meta['route']}")
            with cols[1]:
                if "vector_count" in meta:
                    st.caption(f"📄 Sources: {meta['vector_count']} chunks")
            with cols[2]:
                if "sql_query" in meta:
                    st.caption(f"🗃️ SQL rows: {meta.get('sql_rows', 'N/A')}")

            # Expandable SQL query
            if "sql_query" in meta:
                with st.expander("View SQL Query"):
                    st.code(meta["sql_query"], language="sql")

            # Expandable source documents
            if "sources" in meta:
                with st.expander("View Source Documents"):
                    for i, src in enumerate(meta["sources"]):
                        st.markdown(f"**{i+1}. {src['title']}** ({src['publication_date']})")
                        st.caption(f"Relevance: {src['score']:.3f} | [View Report]({src['report_url']})")
                        st.markdown(f"> {src['text'][:300]}...")
                        st.divider()


# Handle preset questions from sidebar
if "preset_question" in st.session_state:
    prompt = st.session_state.pop("preset_question")
else:
    prompt = st.chat_input("Ask about disease outbreaks...")

# Process the question
if prompt:
    # Add user message to chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Generate response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing outbreak data..."):
            try:
                agent = load_agent()
                result = agent.query(prompt)

                # Display the answer
                st.markdown(result["answer"])

                # Build metadata
                metadata = {"route": result["route"]}

                if "vector_results" in result["sources"]:
                    metadata["vector_count"] = len(result["sources"]["vector_results"])
                    metadata["sources"] = result["sources"]["vector_results"]

                if "sql_result" in result["sources"]:
                    sql_data = result["sources"]["sql_result"]
                    metadata["sql_query"] = sql_data.get("sql", "")
                    metadata["sql_rows"] = sql_data.get("row_count", 0)

                # Show metadata
                cols = st.columns(3)
                with cols[0]:
                    route_emoji = {"VECTOR": "🔍", "SQL": "📊", "HYBRID": "🔀"}
                    st.caption(f"{route_emoji.get(result['route'], '❓')} Route: {result['route']}")
                with cols[1]:
                    if "vector_results" in result["sources"]:
                        st.caption(f"📄 Sources: {len(result['sources']['vector_results'])} chunks")
                with cols[2]:
                    if "sql_result" in result["sources"]:
                        st.caption(f"🗃️ SQL rows: {sql_data.get('row_count', 'N/A')}")

                if "sql_result" in result["sources"] and sql_data.get("sql"):
                    with st.expander("View SQL Query"):
                        st.code(sql_data["sql"], language="sql")

                if "vector_results" in result["sources"]:
                    with st.expander("View Source Documents"):
                        for i, src in enumerate(result["sources"]["vector_results"]):
                            st.markdown(f"**{i+1}. {src['title']}** ({src['publication_date']})")
                            st.caption(f"Relevance: {src['score']:.3f} | [View Report]({src['report_url']})")
                            st.markdown(f"> {src['text'][:300]}...")
                            st.divider()

                # Save to chat history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "metadata": metadata,
                })

            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Sorry, I encountered an error: {str(e)}",
                })