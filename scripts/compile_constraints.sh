#!/usr/bin/env bash
#
# Regenerate constraints/general-chat.txt, the pinned dependency set consumed
# by Dockerfile.general-chat and Dockerfile.controlled-source-chat.
#
# Usage (from anywhere; requires `uv` on PATH):
#   bash scripts/compile_constraints.sh            # re-resolve, keep current pins
#   bash scripts/compile_constraints.sh --upgrade  # move every pin to newest allowed
#
# The resolution targets the production runtime (CPython 3.13 on Linux x86_64),
# not the machine running this script. After an --upgrade run, audit the result
# before committing:
#   uvx pip-audit -r constraints/general-chat.txt --no-deps --disable-pip
#   uvx pip-audit -r constraints/general-chat.txt --no-deps --disable-pip -s osv
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

UPGRADE=""
if [ "${1:-}" = "--upgrade" ]; then
  UPGRADE="--upgrade"
fi

# shellcheck disable=SC2086
uv pip compile constraints/general-chat.in \
  --python-version 3.13 \
  --python-platform x86_64-manylinux_2_28 \
  --no-emit-package openbench \
  --no-emit-package general-chat \
  --no-emit-package controlled-source-chat \
  --custom-compile-command "bash scripts/compile_constraints.sh" \
  $UPGRADE \
  -o constraints/general-chat.txt
