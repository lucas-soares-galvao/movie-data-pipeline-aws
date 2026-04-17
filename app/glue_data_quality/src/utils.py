"""Shared utility functions for the Data Quality app."""


def has_required_columns(columns, required_columns):
    """Check if all required columns are present in the dataset."""
    return set(required_columns).issubset(set(columns))
