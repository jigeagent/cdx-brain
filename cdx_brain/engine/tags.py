# -*- coding: utf-8 -*-
"""Tag filtering system with parameterized SQL (O7: SQL injection fix)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal

TagsMatch = Literal["any", "all"]


@dataclass
class TagGroup:
    """Compound boolean tag filter group."""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    mode: TagsMatch = "any"


def filter_results_by_tags(
    results: list[dict | Any],
    tags: list[str] | None = None,
    match: TagsMatch = "any",
    tag_key: str = "tags",
) -> list[dict | Any]:
    if not tags:
        return results
    filtered = []
    for r in results:
        item_tags = r.get(tag_key, []) if hasattr(r, "get") else getattr(r, tag_key, [])
        if not isinstance(item_tags, list):
            item_tags = []
        if match == "any":
            if any(t in item_tags for t in tags):
                filtered.append(r)
        else:
            if all(t in item_tags for t in tags):
                filtered.append(r)
    return filtered


def filter_results_by_tag_groups(
    results: list[dict | Any],
    tag_groups: list[TagGroup] | None = None,
    tag_key: str = "tags",
) -> list[dict | Any]:
    if not tag_groups:
        return results
    filtered = results
    for group in tag_groups:
        if group.include:
            filtered = filter_results_by_tags(filtered, group.include, group.mode, tag_key)
        if group.exclude:
            filtered = [
                r for r in filtered
                if not any(
                    t in (r.get(tag_key, []) if hasattr(r, "get") else getattr(r, tag_key, []))
                    for t in group.exclude
                )
            ]
    return filtered


def build_tags_where_clause_simple(
    tags: list[str] | None,
    param_offset: int = 0,
    match: TagsMatch = "any",
) -> tuple[str, list[str]]:
    """Parameterized SQL WHERE clause (no f-string injection)."""
    if not tags:
        return "", []
    op = "OR" if match == "any" else "AND"
    clauses = []
    params = []
    for tag in tags:
        clauses.append("," + " || tags || " + "," + " LIKE " + "'%," + " || ? || " + ",%'")
        params.append(tag)
    sql = " AND (" + (" " + op + " ").join(clauses) + ")"
    return sql, params


def build_tag_groups_where_clause(
    tag_groups: list[TagGroup] | None,
    param_offset: int = 0,
) -> tuple[str, list[str]]:
    if not tag_groups:
        return "", []
    all_clauses = []
    all_params = []
    for group in tag_groups:
        group_parts = []

        if group.include:
            op = "OR" if group.mode == "any" else "AND"
            inc_clauses = []
            for tag in group.include:
                inc_clauses.append("," + " || tags || " + "," + " LIKE " + "'%," + " || ? || " + ",%'")
                all_params.append(tag)
            if inc_clauses:
                group_parts.append("(" + (" " + op + " ").join(inc_clauses) + ")")

        if group.exclude:
            for tag in group.exclude:
                group_parts.append("," + " || tags || " + "," + " NOT LIKE " + "'%," + " || ? || " + ",%'")
                all_params.append(tag)

        if group_parts:
            all_clauses.append(" AND ".join(group_parts))

    if not all_clauses:
        return "", []
    return " AND " + " AND ".join(all_clauses), all_params
