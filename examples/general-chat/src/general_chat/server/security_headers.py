"""Response security headers for the single-origin deployment.

The API serves three kinds of documents from one origin, and they need
different treatment:

* the SPA (``index.html``) — trusted code, gets a Content-Security-Policy
  that limits where script, frames and connections may come from, so an
  injected ``<script>`` or ``<iframe>`` in rendered chat content cannot run
  or exfiltrate the Firebase token kept in same-origin storage;
* documents built from model or user input (exported dashboards under
  ``/downloads``, published snapshots under ``/d/{id}``, uploaded HTML/SVG)
  — untrusted markup that must never execute as this origin, so they are
  served with ``sandbox`` (opaque origin, no script);
* everything else — ``nosniff`` so a file is never reinterpreted as HTML.

``GENERAL_CHAT_CSP_MODE`` controls the SPA policy: ``enforce`` (default),
``report-only`` (browser logs violations but does not block; use it for the
first rollout of a policy change) or ``off``. The untrusted-document policy
is always enforced.
"""

from __future__ import annotations

import os

from starlette.responses import Response

CSP_MODE_ENV = "GENERAL_CHAT_CSP_MODE"
CSP_ENFORCE = "enforce"
CSP_REPORT_ONLY = "report-only"
CSP_OFF = "off"

#: Hosts the Firebase Google sign-in popup flow needs.
_FIREBASE_SCRIPT_HOSTS = "https://apis.google.com"
_FIREBASE_CONNECT_HOSTS = (
    "https://identitytoolkit.googleapis.com "
    "https://securetoken.googleapis.com "
    "https://www.googleapis.com "
    "https://apis.google.com"
)
_FIREBASE_FRAME_HOSTS = "https://*.firebaseapp.com https://accounts.google.com"

#: Markup produced from model/user input: opaque origin, nothing executes.
UNTRUSTED_DOCUMENT_CSP = (
    "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
    "img-src data: blob: https:; font-src data: https:; "
    "form-action 'none'; base-uri 'none'"
)

_ACTIVE_DOCUMENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/xml",
    "application/xml",
)


def csp_mode() -> str:
    """Return the configured SPA policy mode; unknown values mean ``enforce``."""
    mode = os.getenv(CSP_MODE_ENV, "").strip().lower()
    return mode if mode in {CSP_ENFORCE, CSP_REPORT_ONLY, CSP_OFF} else CSP_ENFORCE


def spa_csp(*, embeddable: bool = False) -> str:
    """Build the policy for the SPA document.

    Args:
        embeddable: True for ``/embed`` pages, which third-party sites frame
            on purpose; every other page may only be framed by this origin.
    """
    directives = [
        "default-src 'self'",
        # 'wasm-unsafe-eval': the syntax highlighter compiles a WASM regex engine.
        f"script-src 'self' 'wasm-unsafe-eval' {_FIREBASE_SCRIPT_HOSTS}",
        # Inline style attributes come from KaTeX, the highlighter and charts.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "media-src 'self' data: blob:",
        f"connect-src 'self' {_FIREBASE_CONNECT_HOSTS}",
        f"frame-src 'self' blob: data: {_FIREBASE_FRAME_HOSTS}",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    if not embeddable:
        directives.append("frame-ancestors 'self'")
    return "; ".join(directives)


def apply_spa_headers(response: Response, path: str) -> Response:
    """Attach the SPA policy to an ``index.html`` response, honoring the mode."""
    mode = csp_mode()
    if mode == CSP_OFF:
        return response
    header = (
        "Content-Security-Policy-Report-Only"
        if mode == CSP_REPORT_ONLY
        else "Content-Security-Policy"
    )
    response.headers[header] = spa_csp(embeddable=path.startswith("/embed"))
    return response


def is_active_document(content_type: str) -> bool:
    """Whether a response of this content type can run as a document."""
    lowered = (content_type or "").lower()
    return any(kind in lowered for kind in _ACTIVE_DOCUMENT_TYPES)


def apply_untrusted_document_headers(response: Response) -> Response:
    """Sandbox a response whose markup came from model or user input."""
    if is_active_document(response.headers.get("content-type", "")):
        response.headers["Content-Security-Policy"] = UNTRUSTED_DOCUMENT_CSP
    return response


def apply_baseline_headers(response: Response, *, forwarded_proto: str = "") -> Response:
    """Headers every response gets.

    Args:
        response: Outgoing response.
        forwarded_proto: The request's ``X-Forwarded-Proto``. When the public
            hop was HTTPS (TLS terminates at the reverse proxy), browsers are
            told to keep using HTTPS for this host.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if forwarded_proto.strip().lower() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
