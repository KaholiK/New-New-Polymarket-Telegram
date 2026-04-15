#!/usr/bin/env bash
# APEX entrypoint — used by Docker / Railway / Procfile buildpacks.
# Exec so signals reach Python directly (graceful SIGTERM → scheduler shutdown).
set -euo pipefail
exec python -m apex.main
