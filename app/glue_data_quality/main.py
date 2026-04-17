"""Entry point for the Glue Data Quality job."""

from app.glue_data_quality.src.utils import has_required_columns

REQUIRED_COLUMNS = {"id", "title", "release_year"}


def validate_dataset(columns):
    """Return a readable status for required-column validation."""
    if has_required_columns(columns, REQUIRED_COLUMNS):
        return "Dataset approved in data quality validation."
    return "Dataset rejected in data quality validation."


def main():
    # Simple local run example.
    result = validate_dataset({"id", "title", "release_year", "genre"})
    print(result)


if __name__ == "__main__":
    main()
