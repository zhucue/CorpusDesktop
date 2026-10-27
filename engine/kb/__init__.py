"""Knowledge base engine (contracts/p4.md): document parsing, chunking, embeddings, keyword text, term candidates.

parse.parse(source, kind) → (blocks, meta); chunk.chunk(blocks) → chunks; embed.embed(texts) → vectors;
text.tsv_text(text) → space-joined words for PostgreSQL full text; terms.* → term candidates.
"""
