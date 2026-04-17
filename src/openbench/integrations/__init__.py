"""Optional third-party integrations.

Subpackages here wrap external services (Google Drive, Notion, Slack, …)
and ship as **optional extras**. Importing a subpackage is always safe;
using one may require installing the relevant ``[extra]`` from
``pyproject.toml`` (e.g. ``pip install openbench[gdrive]``).

Layout:

- ``openbench.integrations.gdrive`` — Google Drive / Docs backends
"""
