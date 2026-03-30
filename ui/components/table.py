"""
table.py — Reusable data table component.

Wraps st.dataframe with consistent styling and formatting so all pages
display tables the same way without repeating the same options everywhere.

Usage:
    from ui.components.table import render_table
    render_table(rows, column_config={"amount": st.column_config.NumberColumn(...)})
"""

import pandas as pd
import streamlit as st


def render_table(
    rows: list[dict],
    column_config: dict | None = None,
    height: int = 400,
    use_container_width: bool = True,
) -> None:
    """
    Render a list of dicts as a styled dataframe.

    Args:
        rows:               List of dicts — each dict is one row.
        column_config:      Optional Streamlit column config dict for custom
                            formatting (number formats, labels, etc.).
        height:             Pixel height of the table widget.
        use_container_width: Stretch the table to fill the column width.
    """
    if not rows:
        st.info("No data to display.")
        return

    dataframe = pd.DataFrame(rows)
    st.dataframe(
        dataframe,
        column_config=column_config,
        height=height,
        use_container_width=use_container_width,
        hide_index=True,
    )


def amount_column(label: str, help_text: str = "") -> st.column_config.NumberColumn:
    """Return a pre-configured NumberColumn for Malaysian Ringgit amounts."""
    return st.column_config.NumberColumn(
        label=label,
        help=help_text,
        format="RM %.2f",
        min_value=0,
    )


def date_column(label: str) -> st.column_config.DateColumn:
    """Return a pre-configured DateColumn."""
    return st.column_config.DateColumn(label=label, format="YYYY-MM-DD")


def status_column(label: str = "Status") -> st.column_config.TextColumn:
    """Return a text column for reconciliation status values."""
    return st.column_config.TextColumn(label=label)