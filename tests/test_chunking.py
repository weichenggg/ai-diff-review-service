import asyncio

from app.chunking import CHUNK_BYTES, chunk_unified_diff
from app.main import process_review_job


def file_diff(path: str, line_number: int, addition: str, padding_bytes: int = 0) -> str:
    padding = f"-{'.' * padding_bytes}\n" if padding_bytes else ""
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +{line_number} @@
{padding}+{addition}
"""


def process(diff: str, max_findings: int = 100) -> dict[str, object]:
    job: dict[str, object] = {"status": "queued"}
    asyncio.run(process_review_job(job, diff, max_findings))
    return job


def test_diff_at_or_below_64_kib_uses_one_chunk() -> None:
    diff = file_diff("small.ts", 1, "console.log('small');")

    job = process(diff)

    assert len(diff.encode("utf-8")) <= CHUNK_BYTES
    assert chunk_unified_diff(diff) == [diff]
    assert job["usage"]["chunks"] == 1  # type: ignore[index]


def test_multiple_files_over_64_kib_are_split_into_multiple_chunks() -> None:
    diff = (
        file_diff("first.ts", 1, "const first = 1;", padding_bytes=35_000)
        + file_diff("second.ts", 1, "const second = 2;", padding_bytes=35_000)
    )

    chunks = chunk_unified_diff(diff)
    job = process(diff)

    assert len(diff.encode("utf-8")) > CHUNK_BYTES
    assert len(chunks) == 2
    assert all(len(chunk.encode("utf-8")) <= CHUNK_BYTES for chunk in chunks)
    assert job["usage"]["chunks"] == 2  # type: ignore[index]


def test_a_single_file_larger_than_64_kib_remains_one_chunk() -> None:
    diff = file_diff("large.ts", 1, "console.log('large');", padding_bytes=CHUNK_BYTES)

    chunks = chunk_unified_diff(diff)
    job = process(diff)

    assert len(diff.encode("utf-8")) > CHUNK_BYTES
    assert chunks == [diff]
    assert job["usage"]["chunks"] == 1  # type: ignore[index]


def test_findings_are_identical_with_and_without_chunking() -> None:
    small_diff = (
        file_diff("a.ts", 4, "eval(input);")
        + file_diff("z.ts", 9, "console.log('debug');")
    )
    chunked_diff = (
        file_diff("a.ts", 4, "eval(input);", padding_bytes=35_000)
        + file_diff("z.ts", 9, "console.log('debug');", padding_bytes=35_000)
    )

    small_job = process(small_diff)
    chunked_job = process(chunked_diff)

    assert small_job["findings"] == chunked_job["findings"]
    assert chunked_job["usage"]["chunks"] == 2  # type: ignore[index]


def test_merged_findings_are_globally_ordered_after_chunking() -> None:
    diff = (
        file_diff("z.ts", 9, "console.log('debug');", padding_bytes=35_000)
        + file_diff("a.ts", 4, "eval(input);", padding_bytes=35_000)
    )

    job = process(diff)

    assert [finding.id for finding in job["findings"]] == [  # type: ignore[index]
        "MOCK-001:a.ts:4",
        "MOCK-007:z.ts:9",
    ]


def test_max_findings_is_applied_after_global_merge_and_sort() -> None:
    diff = (
        file_diff("z.ts", 9, "console.log('debug');", padding_bytes=35_000)
        + file_diff("a.ts", 4, "eval(input);", padding_bytes=35_000)
    )

    job = process(diff, max_findings=1)

    assert [finding.id for finding in job["findings"]] == ["MOCK-001:a.ts:4"]  # type: ignore[index]
