"""Markdown table helper — avoids a tabulate dependency."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _cell(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def dataframe_to_markdown(frame: pd.DataFrame) -> str:
    headers = [str(c) for c in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines)
