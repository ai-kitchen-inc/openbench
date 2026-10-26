"""Demo: load a BaseAgent's persona from a Google Doc.

Setup (one-time):

1. Create a Google Cloud service account and download its JSON key.
   https://console.cloud.google.com/iam-admin/serviceaccounts

2. Enable the Google Docs API for that project.
   https://console.cloud.google.com/apis/library/docs.googleapis.com

3. Create a Google Doc and share it (Reader access) with the service
   account's email (looks like ``foo@project-name.iam.gserviceaccount.com``).

4. Structure the Doc with three H1 headings — ``SOUL``, ``STYLE``,
   ``AGENTS`` — and put the corresponding persona content under each.

5. Copy the document id out of the URL:
   ``https://docs.google.com/document/d/<DOC_ID>/edit``.

Run:

    pip install 'openbench[gdrive]'
    export GOOGLE_SERVICE_ACCOUNT=/path/to/service-account.json
    export GOOGLE_DOC_ID=1ABCdef...
    python examples/chat/gdoc_persona_demo.py

The demo only prints the composed persona — it does not start a server
or call an LLM — so you can verify your Doc is parsed correctly before
wiring the source into a real agent.
"""

from __future__ import annotations

import os
import sys

from openbench.integrations.gdrive import GoogleDocPersonaSource
from openbench.intelligence.persona import Persona


def main() -> int:
    sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT")
    doc_id = os.environ.get("GOOGLE_DOC_ID")
    if not sa or not doc_id:
        print(
            "Set GOOGLE_SERVICE_ACCOUNT and GOOGLE_DOC_ID env vars. "
            "See this file's module docstring for setup steps.",
            file=sys.stderr,
        )
        return 1

    source = GoogleDocPersonaSource(
        doc_id=doc_id,
        service_account_file=sa,
    )

    persona = Persona.from_source(source)
    summary = persona.summary()

    print(f"Source : {persona.source}")
    print(f"Doc id : {source.doc_id}")
    print(f"SOUL   : {summary['soul_chars']:>5} chars")
    print(f"STYLE  : {summary['style_chars']:>5} chars")
    print(f"AGENTS : {summary['agents_chars']:>5} chars")
    print(f"Total  : {summary['total_chars']:>5} chars")
    print()
    print("── Composed persona ──")
    print(persona.compose() or "(empty — check that your Doc has H1 SOUL/STYLE/AGENTS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
