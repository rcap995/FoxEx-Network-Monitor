"""Thin dataclass wrappers around sqlite3.Row dicts — no ORM."""
from dataclasses import dataclass, field
from typing import Optional


def row_to_dict(row) -> dict:
    return dict(row) if row else {}


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
