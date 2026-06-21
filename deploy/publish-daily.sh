#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# publish-daily.sh — Daily noise graph generation and GitHub Pages publishing
#
# Generates a noise graph for yesterday, copies it to a gh-pages checkout,
# regenerates index.html, and pushes to the gh-pages branch.
#
# Idempotent: running multiple times on the same day does nothing.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- Configuration ----------------------------------------------------------
REPO_DIR="/home/pi/noise-catcher"
VENV_DIR="${REPO_DIR}/.venv"
NOISE_CATCHER_BIN="${VENV_DIR}/bin/noise-catcher"
DB_PATH="${REPO_DIR}/noise_catcher.db"
TEMPLATE_FILE="${REPO_DIR}/deploy/index.template.html"
GH_PAGES_DIR="${HOME}/noise-catcher-gh-pages"
REPO_URL="git@github.com:coldsoul/noise-catcher.git"

# --- Compute yesterday's date (cross-platform) -----------------------------
if date -v-1d >/dev/null 2>&1; then
    # macOS
    YESTERDAY=$(date -v-1d +%Y-%m-%d)
else
    # Linux
    YESTERDAY=$(date -d "yesterday" +%Y-%m-%d)
fi

OUTPUT_FILE="/tmp/noise_${YESTERDAY}.png"
TIMESTAMP=$(date -u "+%Y-%m-%d %H:%M:%S UTC")

echo "[${TIMESTAMP}] Publishing noise graph for ${YESTERDAY}..."

# --- Generate graph ---------------------------------------------------------
if [[ ! -x "${NOISE_CATCHER_BIN}" ]]; then
    echo "ERROR: noise-catcher not found at ${NOISE_CATCHER_BIN}" >&2
    exit 1
fi

"${NOISE_CATCHER_BIN}" graph \
    --db "${DB_PATH}" \
    --date "${YESTERDAY}" \
    --output "${OUTPUT_FILE}"

echo "Graph generated: ${OUTPUT_FILE}"

# --- Ensure gh-pages checkout ------------------------------------------------
if [[ ! -d "${GH_PAGES_DIR}" ]]; then
    echo "Setting up gh-pages checkout at ${GH_PAGES_DIR}..."
    mkdir -p "${GH_PAGES_DIR}"
    git -C "${GH_PAGES_DIR}" init
    git -C "${GH_PAGES_DIR}" remote add origin "${REPO_URL}"

    if git -C "${GH_PAGES_DIR}" fetch origin gh-pages 2>/dev/null; then
        git -C "${GH_PAGES_DIR}" checkout gh-pages
        echo "Checked out existing gh-pages branch."
    else
        # Create gh-pages branch from scratch
        git -C "${GH_PAGES_DIR}" checkout --orphan gh-pages
        git -C "${GH_PAGES_DIR}" commit --allow-empty -m "Initialize gh-pages"
        git -C "${GH_PAGES_DIR}" push origin gh-pages
        echo "Created and pushed gh-pages branch."
    fi
else
    git -C "${GH_PAGES_DIR}" pull origin gh-pages
    echo "Updated gh-pages checkout."
fi

# --- Idempotency check ------------------------------------------------------
if [[ -f "${GH_PAGES_DIR}/graphs/noise_${YESTERDAY}.png" ]]; then
    echo "Graph for ${YESTERDAY} already published. Nothing to do."
    exit 0
fi

# --- Copy graph into gh-pages checkout --------------------------------------
mkdir -p "${GH_PAGES_DIR}/graphs"
cp "${OUTPUT_FILE}" "${GH_PAGES_DIR}/graphs/noise_${YESTERDAY}.png"
echo "Graph copied to ${GH_PAGES_DIR}/graphs/."

# --- Generate index.html -----------------------------------------------------
if [[ -f "${TEMPLATE_FILE}" ]]; then
    sed -e "s|{{DATE}}|${YESTERDAY}|g" \
        -e "s|{{IMAGE_PATH}}|graphs/noise_${YESTERDAY}.png|g" \
        -e "s|{{TIMESTAMP}}|${TIMESTAMP}|g" \
        "${TEMPLATE_FILE}" > "${GH_PAGES_DIR}/index.html"
    echo "index.html generated from template."
else
    echo "WARNING: Template not found at ${TEMPLATE_FILE}, generating minimal index.html"
    cat > "${GH_PAGES_DIR}/index.html" <<HTMLEOF
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Noise Catcher</title></head>
<body>
<h1>Noise Catcher — ${YESTERDAY}</h1>
<img src="graphs/noise_${YESTERDAY}.png" alt="Noise graph for ${YESTERDAY}">
<p>Last updated: ${TIMESTAMP}</p>
<p><a href="https://github.com/coldsoul/noise-catcher">GitHub</a></p>
</body>
</html>
HTMLEOF
    echo "Minimal index.html generated."
fi

# --- Commit and push --------------------------------------------------------
git -C "${GH_PAGES_DIR}" add -A

if git -C "${GH_PAGES_DIR}" diff --cached --quiet; then
    echo "No changes to commit."
else
    git -C "${GH_PAGES_DIR}" commit -m "Publish ${YESTERDAY} noise graph"
    git -C "${GH_PAGES_DIR}" push origin gh-pages
    echo "Published graph for ${YESTERDAY} to gh-pages."
fi
