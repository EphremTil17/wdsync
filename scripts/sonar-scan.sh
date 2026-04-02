#!/usr/bin/env bash
# Run SonarQube scanner using credentials from .env
# Usage: ./scripts/sonar-scan.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "error: .env not found. Create it with SONARQUBE_URL and SONARQUBE_TOKEN." >&2
    exit 1
fi
set -a
# shellcheck source=/dev/null
source "$PROJECT_ROOT/.env"
set +a

if [[ -z "${SONARQUBE_TOKEN:-}" ]]; then
    echo "error: SONARQUBE_TOKEN not set in .env" >&2
    exit 1
fi

# Generate coverage report
echo "Generating coverage report..."
uv run pytest --cov-report=xml -q

# Rewrite paths for SonarQube (expects src-relative, not absolute)
if [[ -f coverage.xml ]]; then
    sed -i "s|<source>.*</source>|<source>.</source>|g" coverage.xml
fi

# Run scanner
echo "Running SonarQube scanner..."
docker run --rm \
    --network host \
    -e SONAR_HOST_URL="$SONARQUBE_URL" \
    -e SONAR_TOKEN="$SONARQUBE_TOKEN" \
    -v "$PROJECT_ROOT:/usr/src" \
    sonarsource/sonar-scanner-cli
