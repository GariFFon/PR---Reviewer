"""Parse a unified diff and answer "was this line touched by the PR?"

Findings from both Semgrep and the LLM get filtered through this before
they're allowed anywhere near GitHub — nothing gets reported on a line the
PR didn't change.
"""

from dataclasses import dataclass, field

from unidiff import PatchSet


@dataclass
class FileDiff:
    path: str
    is_added: bool
    is_removed: bool
    changed_lines: set[int] = field(default_factory=set)  # line numbers in the new file

    def is_line_changed(self, line: int) -> bool:
        return line in self.changed_lines

    def overlaps_changed_range(self, start: int, end: int) -> bool:
        return any(start <= line <= end for line in self.changed_lines)

    def changed_ranges(self) -> list[tuple[int, int]]:
        """Collapse the changed-line set into contiguous (start, end) ranges."""
        if not self.changed_lines:
            return []
        lines = sorted(self.changed_lines)
        ranges: list[tuple[int, int]] = []
        start = prev = lines[0]
        for line in lines[1:]:
            if line == prev + 1:
                prev = line
                continue
            ranges.append((start, prev))
            start = prev = line
        ranges.append((start, prev))
        return ranges


def parse_diff(diff_text: str) -> dict[str, FileDiff]:
    """Parse a unified diff (as returned by GitHub's `.diff` media type)
    into a per-file map of changed line numbers on the new (right) side."""
    patch = PatchSet(diff_text)
    result: dict[str, FileDiff] = {}

    for patched_file in patch:
        if patched_file.is_binary_file:
            continue
        path = patched_file.path
        file_diff = FileDiff(
            path=path,
            is_added=patched_file.is_added_file,
            is_removed=patched_file.is_removed_file,
        )
        for hunk in patched_file:
            for line in hunk:
                if line.is_added and line.target_line_no is not None:
                    file_diff.changed_lines.add(line.target_line_no)
        result[path] = file_diff

    return result
