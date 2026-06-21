"""Tests for the daily publish script logic.

Tests date computation, idempotency detection, template substitution,
and git commit logic in isolation (no real pushes).
"""

import subprocess
from datetime import date, timedelta
from pathlib import Path

# ============================================================================
# Helpers
# ============================================================================


def _setup_git_repo(path: Path) -> Path:
    """Initialize a git repo with an initial commit for testing."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        cwd=path, capture_output=True, check=True,
    )
    return path


def _count_commits(repo: Path) -> int:
    """Return the number of commits in a git repo."""
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return int(result.stdout.strip())


# ============================================================================
# Tests
# ============================================================================


class TestDateComputation:
    """Yesterday's date in YYYY-MM-DD format."""

    def test_macos_date_v_1d(self) -> None:
        """date -v-1d +%Y-%m-%d returns yesterday in YYYY-MM-DD."""
        result = subprocess.run(
            ["date", "-v-1d", "+%Y-%m-%d"],
            capture_output=True, text=True, check=True,
        )
        expected = (date.today() - timedelta(days=1)).isoformat()
        assert result.stdout.strip() == expected

    def test_cross_platform_fallback(self) -> None:
        """Both macOS and Linux date branches produce the same result."""
        script = """
if date -v-1d >/dev/null 2>&1; then
    date -v-1d +%Y-%m-%d
else
    date -d "yesterday" +%Y-%m-%d
fi
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, check=True,
        )
        expected = (date.today() - timedelta(days=1)).isoformat()
        assert result.stdout.strip() == expected

    def test_date_format_is_yyyy_mm_dd(self) -> None:
        """Output matches the YYYY-MM-DD pattern."""
        result = subprocess.run(
            ["date", "-v-1d", "+%Y-%m-%d"],
            capture_output=True, text=True, check=True,
        )
        date_str = result.stdout.strip()
        assert len(date_str) == 10  # YYYY-MM-DD
        parts = date_str.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day


class TestTemplateSubstitution:
    """Template variable substitution ({{DATE}}, {{IMAGE_PATH}}, {{TIMESTAMP}})."""

    TEMPLATE_CONTENT = """\
<!DOCTYPE html>
<html>
<head><title>Noise Catcher</title></head>
<body>
<img src="{{IMAGE_PATH}}" alt="Noise graph for {{DATE}}">
<p>Date: {{DATE}}</p>
<p>Last updated: {{TIMESTAMP}}</p>
</body>
</html>"""

    def test_all_variables_replaced(self, tmp_path: Path) -> None:
        """All three template variables are properly substituted."""
        template = tmp_path / "index.template.html"
        template.write_text(self.TEMPLATE_CONTENT)

        output = tmp_path / "index.html"
        date_val = "2026-06-20"
        image_path = "graphs/noise_2026-06-20.png"
        timestamp = "2026-06-21 02:00:00 UTC"

        # Run the same sed commands used by publish-daily.sh
        with open(output, "w") as f:
            subprocess.run(
                [
                    "sed",
                    "-e", f"s|{{{{DATE}}}}|{date_val}|g",
                    "-e", f"s|{{{{IMAGE_PATH}}}}|{image_path}|g",
                    "-e", f"s|{{{{TIMESTAMP}}}}|{timestamp}|g",
                    str(template),
                ],
                check=True, stdout=f,
            )

        content = output.read_text()
        assert date_val in content
        assert image_path in content
        assert timestamp in content
        assert "{{" not in content, "Unsubstituted template variables remain"

    def test_variable_appears_once_per_placeholder(self, tmp_path: Path) -> None:
        """Each variable instance in the template gets substituted."""
        template = tmp_path / "index.template.html"
        template.write_text("{{DATE}} and {{DATE}} again")

        output = tmp_path / "index.html"
        date_val = "2026-06-20"

        with open(output, "w") as f:
            subprocess.run(
                ["sed", "-e", f"s|{{{{DATE}}}}|{date_val}|g", str(template)],
                check=True, stdout=f,
            )

        content = output.read_text()
        assert content.count(date_val) == 2
        assert "{{DATE}}" not in content


class TestIdempotency:
    """Script detects existing graph and skips (idempotency)."""

    def test_existing_graph_skips(self, tmp_path: Path) -> None:
        """When graph file already exists, the script signals skip."""
        graphs_dir = tmp_path / "graphs"
        graphs_dir.mkdir(parents=True)
        graph_file = graphs_dir / "noise_2026-06-20.png"
        graph_file.write_text("dummy-png-content")

        script = f"""
YESTERDAY="2026-06-20"
if [[ -f "{graphs_dir}/noise_${{YESTERDAY}}.png" ]]; then
    echo "EXISTS:SKIP"
else
    echo "MISSING:PROCEED"
fi
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, check=True,
        )
        assert "EXISTS:SKIP" in result.stdout
        assert "MISSING" not in result.stdout

    def test_missing_graph_proceeds(self, tmp_path: Path) -> None:
        """When graph file is absent, the script proceeds."""
        graphs_dir = tmp_path / "graphs"
        graphs_dir.mkdir(parents=True)
        # No graph file created

        script = f"""
YESTERDAY="2026-06-20"
if [[ -f "{graphs_dir}/noise_${{YESTERDAY}}.png" ]]; then
    echo "EXISTS:SKIP"
else
    echo "MISSING:PROCEED"
fi
"""
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, check=True,
        )
        assert "MISSING:PROCEED" in result.stdout


class TestGitOperations:
    """Git commit logic — only commit when there are actual changes."""

    def test_no_commit_when_no_changes(self, tmp_path: Path) -> None:
        """No commit is created when nothing changed."""
        repo = _setup_git_repo(tmp_path)
        initial_commits = _count_commits(repo)

        result = subprocess.run(
            [
                "bash", "-c",
                r"""
cd "$1"
git add -A 2>/dev/null
if git diff --cached --quiet 2>/dev/null; then
    echo "NO_CHANGES"
else
    git commit -m "should not happen" 2>/dev/null || true
    echo "HAD_CHANGES"
fi
""",
                "_", str(repo),
            ],
            capture_output=True, text=True,
        )
        assert "NO_CHANGES" in result.stdout
        assert _count_commits(repo) == initial_commits

    def test_commit_when_new_files_added(self, tmp_path: Path) -> None:
        """A commit is created when new files exist."""
        repo = _setup_git_repo(tmp_path)
        initial_commits = _count_commits(repo)

        (repo / "test.txt").write_text("new content")

        result = subprocess.run(
            [
                "bash", "-c",
                r"""
cd "$1"
git add -A
if git diff --cached --quiet 2>/dev/null; then
    echo "NO_CHANGES"
else
    git commit -m "test commit" 2>/dev/null || true
    echo "COMMITTED"
fi
""",
                "_", str(repo),
            ],
            capture_output=True, text=True,
        )
        assert "COMMITTED" in result.stdout
        assert _count_commits(repo) == initial_commits + 1

    def test_commit_with_specific_message(self, tmp_path: Path) -> None:
        """Commit message contains the date."""
        repo = _setup_git_repo(tmp_path)

        (repo / "graph.png").write_text("fake-graph")

        subprocess.run(
            [
                "bash", "-c",
                r"""
cd "$1"
git add -A
git commit -m "Publish 2026-06-20 noise graph" 2>/dev/null || true
""",
                "_", str(repo),
            ],
            capture_output=True, text=True, check=True,
        )

        log_result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo, capture_output=True, text=True, check=True,
        )
        assert "2026-06-20" in log_result.stdout


class TestScriptStructure:
    """Structural tests for the publish-daily.sh script."""

    def test_script_has_set_euo_pipefail(self) -> None:
        """The publish script uses set -euo pipefail."""
        script_path = Path(__file__).resolve().parent.parent / "deploy" / "publish-daily.sh"
        content = script_path.read_text()
        assert "set -euo pipefail" in content

    def test_script_is_executable(self) -> None:
        """The publish script is executable."""
        script_path = Path(__file__).resolve().parent.parent / "deploy" / "publish-daily.sh"
        assert script_path.stat().st_mode & 0o111, "Script is not executable"
