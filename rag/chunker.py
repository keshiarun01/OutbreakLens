"""
WHO Report Chunker
===================
Breaks WHO Disease Outbreak News reports into smaller, meaningful
chunks for vector embedding and semantic search.

Why chunk?
  - LLMs have limited context windows
  - Smaller chunks = more precise retrieval
  - Each chunk can carry its own metadata for filtered search

Chunking Strategy:
  - Split on paragraph boundaries (double newlines)
  - Merge small paragraphs together until we hit ~500 chars
  - Add overlap between chunks so context isn't lost at boundaries
  - Attach metadata (report_id, title, date, URL) to every chunk
"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """Represents one chunk of text with its metadata."""
    text: str
    metadata: dict = field(default_factory=dict)


def clean_text(text: str) -> str:
    """
    Cleans raw text from WHO reports:
      - Remove leftover HTML entities (&amp;, &nbsp;, etc.)
      - Normalize whitespace
      - Remove excessive newlines
    """
    if not text:
        return ""

    # Remove HTML entities
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    # Remove any remaining HTML tags (just in case)
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Normalize newlines (3+ newlines → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_into_paragraphs(text: str) -> list[str]:
    """
    Splits text into paragraphs on double newlines.
    Filters out empty or very short paragraphs.
    """
    paragraphs = re.split(r"\n\n+", text)
    # Keep only paragraphs with meaningful content (> 30 chars)
    return [p.strip() for p in paragraphs if len(p.strip()) > 30]


def merge_small_paragraphs(
    paragraphs: list[str],
    target_size: int = 500,
    max_size: int = 1000,
) -> list[str]:
    """
    Merges consecutive small paragraphs into larger chunks.

    Why? A single paragraph might be just one sentence like
    "The outbreak was first reported on 15 January." — too short
    to be a useful chunk on its own. We merge it with neighbors
    until we reach ~500 characters.

    Parameters:
        target_size: ideal chunk size in characters
        max_size: never exceed this size
    """
    if not paragraphs:
        return []

    chunks = []
    current_chunk = paragraphs[0]

    for para in paragraphs[1:]:
        # If adding this paragraph keeps us under max, merge
        if len(current_chunk) + len(para) + 2 <= max_size:
            current_chunk += "\n\n" + para
        else:
            # Current chunk is big enough, save it and start new one
            chunks.append(current_chunk)
            current_chunk = para

    # Don't forget the last chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def add_overlap(chunks: list[str], overlap_chars: int = 100) -> list[str]:
    """
    Adds overlap between consecutive chunks.

    Why overlap? If a key fact spans two chunks, overlap ensures
    both chunks contain that fact. Without overlap, you might
    miss relevant context at chunk boundaries.

    Example with overlap=100:
      Chunk 1: "...the outbreak spread to 5 provinces."
      Chunk 2: "spread to 5 provinces. The WHO deployed..."
                ^^^^^^^^^^^^^^^^^^^^^^^^^ (overlap)
    """
    if len(chunks) <= 1:
        return chunks

    overlapped = [chunks[0]]
    for i in range(1, len(chunks)):
        # Take the last N characters from the previous chunk
        prev_tail = chunks[i - 1][-overlap_chars:]
        # Find a clean word boundary to start the overlap
        space_idx = prev_tail.find(" ")
        if space_idx > 0:
            prev_tail = prev_tail[space_idx + 1:]
        overlapped.append(prev_tail + " " + chunks[i])

    return overlapped


def chunk_report(
    report_id: str,
    title: str,
    summary_text: str,
    overview_text: str,
    publication_date: str,
    report_url: str,
    target_chunk_size: int = 500,
    overlap_chars: int = 100,
) -> list[Chunk]:
    """
    Main chunking function. Takes a single WHO report and returns
    a list of Chunk objects ready for embedding.

    Steps:
      1. Combine and clean the text fields
      2. Split into paragraphs
      3. Merge small paragraphs into target-sized chunks
      4. Add overlap between chunks
      5. Attach metadata to each chunk
    """
    # Combine available text fields
    full_text = ""
    if title:
        full_text += title + "\n\n"
    if overview_text:
        full_text += overview_text + "\n\n"
    if summary_text:
        full_text += summary_text

    # Clean the text
    full_text = clean_text(full_text)

    if not full_text or len(full_text) < 50:
        return []

    # Split → merge → overlap
    paragraphs = split_into_paragraphs(full_text)
    if not paragraphs:
        # If no paragraph breaks, treat the whole text as one chunk
        paragraphs = [full_text]

    merged = merge_small_paragraphs(paragraphs, target_size=target_chunk_size)
    final_texts = add_overlap(merged, overlap_chars=overlap_chars)

    # Create Chunk objects with metadata
    chunks = []
    for i, text in enumerate(final_texts):
        chunk = Chunk(
            text=text,
            metadata={
                "report_id": report_id,
                "title": title or "",
                "publication_date": str(publication_date) if publication_date else "",
                "report_url": report_url or "",
                "chunk_index": i,
                "total_chunks": len(final_texts),
                "source": "who_don",
            },
        )
        chunks.append(chunk)

    return chunks