"""Parquet-backed tabular storage and guarded SQL for uploaded data files.

Uploaded spreadsheets become Parquet tables plus a compact schema card,
so the agent reasons about the shape of the data in the prompt and runs
SQL for the values instead of reading rows as text.
"""

from openbench.data.tabular.catalog import (
    DEFAULT_TABLE_CATALOG_TABLE,
    PostgresTableCatalog,
    SQLiteTableCatalog,
    TableCatalog,
    build_table_catalog,
)
from openbench.data.tabular.converter import (
    TABULAR_EXTENSIONS,
    TableArtifact,
    TableColumn,
    convert_to_parquet,
    is_tabular_file,
)
from openbench.data.tabular.query import (
    DuckDBQueryEngine,
    QueryResult,
    SQLGuardError,
    strip_sql_comments,
    validate_sql,
)

__all__ = [
    # Conversion
    "TABULAR_EXTENSIONS",
    "TableArtifact",
    "TableColumn",
    "convert_to_parquet",
    "is_tabular_file",
    # Catalog
    "DEFAULT_TABLE_CATALOG_TABLE",
    "PostgresTableCatalog",
    "SQLiteTableCatalog",
    "TableCatalog",
    "build_table_catalog",
    # Query
    "DuckDBQueryEngine",
    "QueryResult",
    "SQLGuardError",
    "strip_sql_comments",
    "validate_sql",
]
