"""Sales Analytics — SDK skills demo for OpenBench.

A minimal example demonstrating that OpenBench SDK skills work out of
the box for ANY tabular data domain — no project skills needed.

Uses only:
- Persona (soul/) for analyst identity
- SDK skills: data-context-extractor, query-explorer, data-visualization,
  export-excel, web-search

No xql, no domain-specific config, no aliases.yaml. The column profile
system handles column mapping dynamically via LLM inference.
"""

from sales_analytics.agent import create_analyst_agent

__all__ = ["create_analyst_agent"]
