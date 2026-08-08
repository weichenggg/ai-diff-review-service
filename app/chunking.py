"""Chunk unified diffs without splitting an individual file diff."""


CHUNK_BYTES = 65_536


def split_file_diffs(diff: str) -> list[str]:
    """Return complete per-file diff sections, preserving all source text."""
    lines = diff.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith("diff --git ")]

    if not starts:
        starts = [
            index
            for index, line in enumerate(lines[:-1])
            if line.startswith("--- ") and lines[index + 1].startswith("+++ ")
        ]
    if not starts:
        return [diff]

    sections: list[str] = []
    for section_index, start in enumerate(starts):
        end = starts[section_index + 1] if section_index + 1 < len(starts) else len(lines)
        prefix = "".join(lines[:start]) if section_index == 0 else ""
        sections.append(prefix + "".join(lines[start:end]))
    return sections


def chunk_unified_diff(diff: str, chunk_bytes: int = CHUNK_BYTES) -> list[str]:
    """Greedily pack whole file diffs into UTF-8 chunks of at most ``chunk_bytes``."""
    if len(diff.encode("utf-8")) <= chunk_bytes:
        return [diff]

    chunks: list[str] = []
    current_chunk = ""
    for file_diff in split_file_diffs(diff):
        if current_chunk and len((current_chunk + file_diff).encode("utf-8")) > chunk_bytes:
            chunks.append(current_chunk)
            current_chunk = ""

        current_chunk += file_diff

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
