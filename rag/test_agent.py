"""
Quick test script for the OutbreakLens RAG Agent.
Run this from your Mac (not inside Docker) to test the agent.

Usage:
    cd ~/outbreaklens
    export OPENAI_API_KEY="your-key-here"
    export QDRANT_HOST="localhost"
    export POSTGRES_HOST="localhost"
    python -m rag.test_agent
"""

import os

# Set defaults for local testing (outside Docker)
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("POSTGRES_HOST", "localhost")

from rag.agent import OutbreakLensAgent


def main():
    agent = OutbreakLensAgent()

    # Test questions — one for each route type
    test_questions = [
        # VECTOR question (qualitative)
        "What are the WHO recommendations for preventing mpox transmission?",

        # SQL question (quantitative)
        "Which countries have the highest total COVID cases?",

        # HYBRID question (both)
        "What are the current active outbreaks and what alert signals have been raised?",
    ]

    for question in test_questions:
        print("\n" + "=" * 60)
        result = agent.query(question)
        print(f"\nAnswer:\n{result['answer']}")
        print(f"\nRoute used: {result['route']}")
        if "vector_results" in result["sources"]:
            print(f"Vector sources: {len(result['sources']['vector_results'])} chunks")
        if "sql_result" in result["sources"]:
            sql = result["sources"]["sql_result"]
            print(f"SQL query: {sql.get('sql', 'N/A')[:100]}...")
        print("=" * 60)


if __name__ == "__main__":
    main()