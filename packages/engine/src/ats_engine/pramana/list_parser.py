"""Bracket-aware parsing for compact requirement lists."""

from __future__ import annotations

import re
from dataclasses import dataclass

_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {value: key for key, value in _OPEN_TO_CLOSE.items()}
_LEADING_CUE = re.compile(r"^(?:(?:including|such\s+as|using|with|e\.g\.|i\.e\.|and|or)\s+)+", re.I)
_CONJUNCTION = re.compile(r"\s+(?:and|or)\s+", re.I)


@dataclass(frozen=True, slots=True)
class ListMember:
    """One exact source member and its half-open character offsets."""

    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class StructuredList:
    """A parent requirement and the children named under it."""

    parent: ListMember
    children: tuple[ListMember, ...]


def parse_structured_lists(text: str) -> tuple[StructuredList, ...]:
    """Return balanced bracket/colon lists found in *text*.

    Delimiters split members only at the list's current depth. Any mismatched
    or unclosed bracket rejects the whole fragment instead of returning a
    plausible-looking but malformed requirement.
    """

    pairs, depth_before = _balanced_pairs(text)
    if pairs is None:
        return ()

    results: list[StructuredList] = []
    for opening, closing in pairs:
        parent = _parent_before(text, opening, depth_before[opening])
        children = _split_members(text, opening + 1, closing, depth_before[opening] + 1)
        if parent is not None and children:
            results.append(StructuredList(parent=parent, children=children))

    for colon in _top_level_colons(text, depth_before):
        parent = _member(text, 0, colon)
        children = _split_members(text, colon + 1, len(text), 0)
        if parent is not None and children:
            results.append(StructuredList(parent=parent, children=children))

    seen: set[tuple[int, int, tuple[tuple[int, int], ...]]] = set()
    deduped: list[StructuredList] = []
    for result in results:
        key = (
            result.parent.start,
            result.parent.end,
            tuple((child.start, child.end) for child in result.children),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(result)
    return tuple(sorted(deduped, key=lambda item: (item.parent.start, item.parent.end)))


def _balanced_pairs(text: str) -> tuple[list[tuple[int, int]], list[int]] | tuple[None, list[int]]:
    stack: list[tuple[str, int]] = []
    pairs: list[tuple[int, int]] = []
    depth_before: list[int] = []
    for index, character in enumerate(text):
        depth_before.append(len(stack))
        if character in _OPEN_TO_CLOSE:
            stack.append((character, index))
        elif character in _CLOSE_TO_OPEN:
            if not stack or stack[-1][0] != _CLOSE_TO_OPEN[character]:
                return None, depth_before
            _opening_character, opening = stack.pop()
            pairs.append((opening, index))
    depth_before.append(len(stack))
    if stack:
        return None, depth_before
    return pairs, depth_before


def _parent_before(text: str, opening: int, depth: int) -> ListMember | None:
    start = 0
    index = opening - 1
    while index >= 0:
        if depth == 0 and text[index] in ".!?\n":
            start = index + 1
            break
        if _depth_at(text, index) == depth and text[index] in ",;/:":
            start = index + 1
            break
        conjunction = _conjunction_ending_at(text, index + 1)
        if conjunction is not None and _depth_at(text, conjunction[0]) == depth:
            start = conjunction[1]
            break
        index -= 1
    return _member(text, start, opening)


def _split_members(text: str, start: int, end: int, base_depth: int) -> tuple[ListMember, ...]:
    boundaries = [start]
    index = start
    while index < end:
        depth = _depth_at(text, index)
        if depth == base_depth and text[index] in ",;/":
            boundaries.extend((index, index + 1))
        elif depth == base_depth:
            conjunction = _CONJUNCTION.match(text, index, end)
            if conjunction is not None:
                boundaries.extend((conjunction.start(), conjunction.end()))
                index = conjunction.end()
                continue
        index += 1
    boundaries.append(end)

    members: list[ListMember] = []
    for member_start, member_end in zip(boundaries[::2], boundaries[1::2], strict=False):
        # A nested list describes the member immediately before it. Return the
        # parent term itself here; its nested children are emitted separately.
        nested = next(
            (
                offset
                for offset in range(member_start, member_end)
                if text[offset] in _OPEN_TO_CLOSE and _depth_at(text, offset) == base_depth
            ),
            member_end,
        )
        member = _member(text, member_start, nested)
        if member is not None:
            members.append(member)
    return tuple(members)


def _member(text: str, start: int, end: int) -> ListMember | None:
    raw = text[start:end]
    leading = len(raw) - len(raw.lstrip())
    trailing = len(raw.rstrip())
    cue = _LEADING_CUE.match(raw[leading:trailing])
    if cue is not None:
        leading += cue.end()
    member_start = start + leading
    member_end = start + trailing
    value = text[member_start:member_end].strip(" :-")
    trim = len(text[member_start:member_end]) - len(text[member_start:member_end].lstrip(" :-"))
    member_start += trim
    member_end = member_start + len(value)
    if not value:
        return None
    return ListMember(text=value, start=member_start, end=member_end)


def _top_level_colons(text: str, depth_before: list[int]) -> list[int]:
    return [index for index, character in enumerate(text) if character == ":" and depth_before[index] == 0]


def _depth_at(text: str, index: int) -> int:
    depth = 0
    for character in text[:index]:
        if character in _OPEN_TO_CLOSE:
            depth += 1
        elif character in _CLOSE_TO_OPEN:
            depth -= 1
    return depth


def _conjunction_ending_at(text: str, end: int) -> tuple[int, int] | None:
    for match in _CONJUNCTION.finditer(text, 0, end):
        if match.end() == end:
            return match.start(), match.end()
    return None


__all__ = ["ListMember", "StructuredList", "parse_structured_lists"]
