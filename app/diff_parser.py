"""Utilities for extracting added lines from unified diffs."""

import re #powerful search tool
from dataclasses import dataclass


HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True) #create class automatically, frozen because parser result never change
class AddedLine:
    """One line added to the new version of a file."""

    lineNumber: int
    content: str


def parse_added_lines(diff: str) -> list[AddedLine]:
    """Return added lines and their line numbers in the new file version."""
    added_lines: list[AddedLine] = [] 
    new_file_line_number: int | None = None

    for line in diff.splitlines():
        hunk_header = HUNK_HEADER_PATTERN.match(line)
        if hunk_header:
            new_file_line_number = int(hunk_header.group(1))
            continue

        if new_file_line_number is None:
            continue

        if line.startswith("+"):
            added_lines.append(
                AddedLine(
                    lineNumber=new_file_line_number,
                    content=line[1:],
                )
            )
            new_file_line_number += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_file_line_number += 1

    return added_lines
