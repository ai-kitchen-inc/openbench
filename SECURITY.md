# Security Policy

## Supported Versions

OpenBench is in active alpha development. Security fixes are applied to the
latest released minor version and the `main` branch.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues privately using one of the following channels:

1. **GitHub Security Advisories** (preferred) — use the
   ["Report a vulnerability"](https://github.com/ai-kitchen-inc/openbench/security/advisories/new)
   button on the repository's Security tab.
2. **Email** — send details to **openbench2026@gmail.com** with the subject
   line `SECURITY: <short description>`.

Please include:

- A description of the vulnerability and its impact.
- Steps to reproduce (proof-of-concept if available).
- Affected version(s) and environment details.
- Any suggested remediation.

## Disclosure Process & Timeline

| Stage                     | Target                          |
| ------------------------- | ------------------------------- |
| Acknowledge receipt       | within **3 business days**      |
| Initial assessment        | within **7 business days**      |
| Fix & coordinated release | typically within **90 days**    |

We follow a **coordinated disclosure** model. We ask that you give us a
reasonable window to release a fix before any public disclosure. We will
credit reporters in the release notes unless you request otherwise.

## Scope

In scope: the `openbench` Python package (`src/openbench`) and the
`@openbench/chat-ui` frontend SDK (`studio/chat-ui`).

Out of scope: third-party dependencies (report those upstream), example
applications under `examples/`, and issues requiring physical access or a
compromised host.

## Handling of Secrets

OpenBench reads provider credentials from environment variables and never
logs them. If you find a code path that leaks credentials, treat it as a
security vulnerability and report it privately as described above.
