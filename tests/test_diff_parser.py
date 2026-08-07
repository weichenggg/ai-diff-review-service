from app.diff_parser import AddedLine, parse_added_lines, parse_added_lines_by_file


def test_extracts_added_lines_at_their_new_file_line_numbers() -> None:
    diff = """@@ -10,3 +10,4 @@
 unchanged
-removed
+added first
 retained
+added second
"""

    assert parse_added_lines(diff) == [
        AddedLine(lineNumber=11, content="added first"),
        AddedLine(lineNumber=13, content="added second"),
    ]


def test_resets_the_line_counter_for_each_hunk() -> None:
    diff = """@@ -1 +1 @@
-before
+after
@@ -20,2 +30,3 @@
 context
+new value
 unchanged
"""

    assert parse_added_lines(diff) == [
        AddedLine(lineNumber=1, content="after"),
        AddedLine(lineNumber=31, content="new value"),
    ]


def test_ignores_file_headers_and_lines_outside_hunks() -> None:
    diff = """diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
+not-in-a-hunk
@@ -1 +1 @@
+actual addition
\\ No newline at end of file
"""

    assert parse_added_lines(diff) == [
        AddedLine(lineNumber=1, content="actual addition"),
    ]


def test_preserves_additions_that_begin_with_a_plus_character() -> None:
    diff = """@@ -1 +1 @@
++value
"""

    assert parse_added_lines(diff) == [AddedLine(lineNumber=1, content="+value")]


def test_groups_added_lines_by_new_file_path() -> None:
    diff = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
+first
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -4 +4 @@
+second
"""

    assert parse_added_lines_by_file(diff) == {
        "a.py": [AddedLine(lineNumber=1, content="first")],
        "b.py": [AddedLine(lineNumber=4, content="second")],
    }
