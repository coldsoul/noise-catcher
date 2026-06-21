"""Historical graphs and web dashboard for noise monitoring.

Generates:
- Archive page (archive.html) with thumbnail navigation grid
- Weekly summary bar chart (weekly_summary.png) — L10/L50/L90 + Leq
- Monthly summary bar chart (monthly_summary.png) — same for 30 days
"""

import glob
import math
import os
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from noise_catcher.storage import NoiseDB

# WHO night noise guideline (2009): 55 dB Lnight
WHO_NIGHT_GUIDELINE_DB = 55


def compute_statistical_levels(leq_values: list[float]) -> dict[str, float]:
    """Compute L10, L50, L90, and Leq from a list of per-second Leq values.

    Args:
        leq_values: List of dB(A) values (e.g., per-second measurements).

    Returns:
        Dict with keys ``L10``, ``L50``, ``L90``, ``Leq``.
        All values are ``0.0`` if the input list is empty.
    """
    if not leq_values:
        return {"L10": 0.0, "L50": 0.0, "L90": 0.0, "Leq": 0.0}

    sorted_vals = sorted(leq_values)
    n = len(sorted_vals)

    arr = np.array(sorted_vals, dtype=np.float64)
    # L10 = exceeded 10 % of the time → 90th percentile
    l10 = float(np.percentile(arr, 90))
    # L50 = median → 50th percentile
    l50 = float(np.percentile(arr, 50))
    # L90 = exceeded 90 % of the time → 10th percentile (background)
    l90 = float(np.percentile(arr, 10))

    # Leq = energy-equivalent level
    energy_sum = sum(10.0 ** (v / 10.0) for v in leq_values)
    leq = 10.0 * math.log10(energy_sum / n)

    return {"L10": l10, "L50": l50, "L90": l90, "Leq": leq}


class DashboardGenerator:
    """Generates the historical dashboard: archive page and summary graphs."""

    def __init__(self, db_path: str, gh_pages_dir: str) -> None:
        self.db_path = db_path
        self.gh_pages_dir = gh_pages_dir
        self.graphs_dir = os.path.join(gh_pages_dir, "graphs")

    # ------------------------------------------------------------------
    # Archive page
    # ------------------------------------------------------------------

    def generate_archive_page(self) -> str:
        """Read all available daily graphs from ``graphs/`` and generate
        ``archive.html`` with a featured latest graph and thumbnail grid.

        Returns:
            Path to the generated ``archive.html``.
        """
        # Discover graph files sorted newest-first
        graph_files = sorted(
            glob.glob(os.path.join(self.graphs_dir, "noise_*.png")),
            reverse=True,
        )

        entries: list[tuple[str, str]] = []
        for gf in graph_files:
            basename = os.path.basename(gf)
            if basename.startswith("noise_") and basename.endswith(".png"):
                date_str = basename[6:-4]  # strip "noise_" and ".png"
                entries.append((date_str, f"graphs/{basename}"))

        html = self._build_archive_html(entries)
        output_path = os.path.join(self.gh_pages_dir, "archive.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def _build_archive_html(
        self, entries: list[tuple[str, str]]
    ) -> str:
        """Build the ``archive.html`` content with dark theme, featured
        image + prev/next, and a thumbnail grid."""
        # ---- Featured (latest) image section ----
        featured_html = ""
        if entries:
            latest_date, latest_img = entries[0]
            # Prev links to second-newest graph file (or index.html if none)
            prev_target = (
                entries[1][1] if len(entries) > 1 else "index.html"
            )
            prev_label = (
                entries[1][0] if len(entries) > 1 else "Latest"
            )
            # No "next" for the latest — it's the most recent
            featured_html = (
                f'<div class="featured-graph">'
                f'  <a href="{latest_img}" target="_blank">'
                f'    <img src="{latest_img}" '
                f'         alt="Noise graph for {latest_date}">'
                f"  </a>"
                f'  <div class="nav-links">'
                f'    <a href="{prev_target}" class="nav-btn" '
                f'       title="{prev_label}">&larr; {prev_label}</a>'
                f'    <span class="featured-date">{latest_date}</span>'
                f'    <span class="nav-btn disabled">Next &rarr;</span>'
                f"  </div>"
                f"</div>"
            )
        else:
            featured_html = (
                '<div class="empty-state">'
                "<p>No graphs available yet.</p>"
                "<p>Daily graphs will appear here once recording begins.</p>"
                "</div>"
            )

        # ---- Thumbnail grid ----
        thumbnails_html = ""
        for date_str, img_path in entries:
            thumbnails_html += (
                f'<a href="{img_path}" class="thumb-link" '
                f'   title="{date_str}" target="_blank">'
                f'  <img src="{img_path}" '
                f'       alt="Noise graph for {date_str}" loading="lazy">'
                f'  <span class="thumb-date">{date_str}</span>'
                f"</a>\n"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Noise Catcher — Archive</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                         Helvetica, Arial, sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 2rem 1rem;
        }}
        header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        h1 {{
            font-size: 2rem;
            font-weight: 300;
            letter-spacing: 0.05em;
            color: #ffffff;
        }}
        h1 span {{ color: #4fc3f7; }}
        .subtitle {{
            color: #888;
            font-size: 0.95rem;
            margin-top: 0.3rem;
        }}
        nav.summary-links {{
            margin-top: 1rem;
            display: flex;
            justify-content: center;
            gap: 1rem;
            flex-wrap: wrap;
        }}
        nav.summary-links a {{
            color: #4fc3f7;
            text-decoration: none;
            padding: 0.4rem 1rem;
            border: 1px solid #4fc3f7;
            border-radius: 6px;
            font-size: 0.9rem;
            transition: background 0.2s;
        }}
        nav.summary-links a:hover {{
            background: rgba(79, 195, 247, 0.1);
            text-decoration: none;
        }}
        .featured-graph {{
            max-width: 1000px;
            margin: 0 auto 2rem;
            background: #16213e;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
        }}
        .featured-graph img {{
            width: 100%;
            height: auto;
            border-radius: 8px;
            display: block;
        }}
        .nav-links {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 1rem;
        }}
        .nav-btn {{
            color: #4fc3f7;
            text-decoration: none;
            padding: 0.5rem 1.2rem;
            border: 1px solid #4fc3f7;
            border-radius: 6px;
            font-size: 0.9rem;
            transition: background 0.2s;
        }}
        .nav-btn:hover {{
            background: rgba(79, 195, 247, 0.15);
            text-decoration: none;
        }}
        .nav-btn.disabled {{
            color: #555;
            border-color: #333;
            cursor: default;
        }}
        .featured-date {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #e0e0e0;
        }}
        .empty-state {{
            text-align: center;
            padding: 4rem 2rem;
            color: #666;
            font-size: 1.2rem;
        }}
        .empty-state p + p {{
            margin-top: 0.5rem;
            font-size: 0.95rem;
            color: #555;
        }}
        .section-title {{
            text-align: center;
            font-weight: 300;
            margin-bottom: 1.5rem;
            color: #888;
        }}
        .thumbnail-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1rem;
            max-width: 1200px;
            margin: 0 auto;
        }}
        .thumb-link {{
            display: block;
            background: #16213e;
            border-radius: 10px;
            padding: 0.75rem;
            text-decoration: none;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
        }}
        .thumb-link:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }}
        .thumb-link img {{
            width: 100%;
            height: auto;
            border-radius: 6px;
            display: block;
        }}
        .thumb-date {{
            display: block;
            text-align: center;
            color: #aaa;
            font-size: 0.85rem;
            margin-top: 0.5rem;
        }}
        footer {{
            margin-top: 2rem;
            text-align: center;
            font-size: 0.8rem;
            color: #555;
        }}
        @media (max-width: 600px) {{
            body {{ padding: 1rem 0.5rem; }}
            h1 {{ font-size: 1.4rem; }}
            .featured-graph {{ padding: 0.75rem; }}
            .thumbnail-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>Noise <span>Catcher</span></h1>
        <p class="subtitle">Historical Noise Archive</p>
        <nav class="summary-links">
            <a href="index.html">Latest</a>
            <a href="weekly_summary.png">Weekly Summary</a>
            <a href="monthly_summary.png">Monthly Summary</a>
        </nav>
    </header>

    <main>
        {featured_html}

        <h2 class="section-title">All Graphs</h2>
        <div class="thumbnail-grid">
            {thumbnails_html}
        </div>
    </main>

    <footer>
        <p><a href="https://github.com/coldsoul/noise-catcher"
              style="color:#4fc3f7;">View on GitHub</a></p>
    </footer>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Summary graphs
    # ------------------------------------------------------------------

    def generate_weekly_summary(self, end_date: date | None = None) -> str:
        """Generate a weekly noise summary graph (last 7 days).

        Args:
            end_date: End date for the summary (default: today).

        Returns:
            Path to the generated PNG file.
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=6)
        daily_stats = self._compute_daily_stats(start_date, end_date)

        output_path = os.path.join(self.gh_pages_dir, "weekly_summary.png")
        self._render_summary_graph(
            daily_stats, "Weekly", start_date, end_date, output_path,
        )
        return output_path

    def generate_monthly_summary(self, end_date: date | None = None) -> str:
        """Generate a monthly noise summary graph (last 30 days).

        Args:
            end_date: End date for the summary (default: today).

        Returns:
            Path to the generated PNG file.
        """
        if end_date is None:
            end_date = date.today()

        start_date = end_date - timedelta(days=29)
        daily_stats = self._compute_daily_stats(start_date, end_date)

        output_path = os.path.join(self.gh_pages_dir, "monthly_summary.png")
        self._render_summary_graph(
            daily_stats, "Monthly", start_date, end_date, output_path,
        )
        return output_path

    def _compute_daily_stats(
        self,
        start_date: date,
        end_date: date,
    ) -> list[tuple[date, dict[str, float]]]:
        """Query the DB for each day's Leq values and compute statistical
        levels (L10, L50, L90, Leq).

        Returns a list of ``(date, levels_dict)`` tuples.
        """
        db = NoiseDB(self.db_path)
        db.initialize()

        stats_list: list[tuple[date, dict[str, float]]] = []
        current = start_date
        while current <= end_date:
            day_start = datetime(
                current.year, current.month, current.day, 0, 0, 0,
            )
            day_end_ts = day_start.timestamp() + 86400
            rows = db.query_range(day_start.timestamp(), day_end_ts)
            leq_values = [float(r[1]) for r in rows if r[1] is not None]

            stats = compute_statistical_levels(leq_values)
            stats_list.append((current, stats))

            current += timedelta(days=1)

        db.close()
        return stats_list

    # ------------------------------------------------------------------
    # Summary graph rendering (shared by weekly & monthly)
    # ------------------------------------------------------------------

    def _render_summary_graph(
        self,
        daily_stats: list[tuple[date, dict[str, float]]],
        label: str,  # "Weekly" or "Monthly"
        start_date: date,
        end_date: date,
        output_path: str,
    ) -> None:
        """Render a grouped bar chart with L10/L50/L90 and overlaid Leq
        line, using the same dark theme as the main page."""
        fig, ax = plt.subplots(figsize=(14, 5))
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#16213e")

        if not daily_stats or all(
            s[1]["L90"] == 0 and s[1]["L50"] == 0 and s[1]["L10"] == 0
            for s in daily_stats
        ):
            ax.text(
                0.5,
                0.5,
                f"No data available for {label.lower()} summary",
                ha="center",
                va="center",
                fontsize=14,
                color="#666",
                transform=ax.transAxes,
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            fig.savefig(output_path, dpi=150, facecolor="#1a1a2e")
            plt.close(fig)
            return

        dates = [s[0] for s in daily_stats]
        l90_vals = [s[1]["L90"] for s in daily_stats]
        l50_vals = [s[1]["L50"] for s in daily_stats]
        l10_vals = [s[1]["L10"] for s in daily_stats]
        leq_vals = [s[1]["Leq"] for s in daily_stats]

        x = np.arange(len(dates))
        bar_width = 0.25

        # Grouped bars
        ax.bar(
            x - bar_width, l90_vals, bar_width,
            label="L90 (Background)", color="#4fc3f7", alpha=0.85,
        )
        ax.bar(
            x, l50_vals, bar_width,
            label="L50 (Median)", color="#ffa726", alpha=0.85,
        )
        ax.bar(
            x + bar_width, l10_vals, bar_width,
            label="L10 (Peak)", color="#ef5350", alpha=0.85,
        )

        # Leq line overlay
        ax.plot(
            x, leq_vals, marker="o", color="#66bb6a",
            linewidth=2, markersize=6,
            label="Leq (Energy-Equivalent)",
        )

        # WHO guideline reference
        ax.axhline(
            y=WHO_NIGHT_GUIDELINE_DB,
            color="red",
            linestyle="--",
            linewidth=1,
            alpha=0.7,
            label=f"WHO Guideline ({WHO_NIGHT_GUIDELINE_DB} dB)",
        )

        # Labels, ticks, styling
        ax.set_xlabel("Date", color="#ccc")
        ax.set_ylabel("Sound Level (dB(A))", color="#ccc")
        ax.set_title(
            f"{label} Noise Summary \u2014 "
            f"{start_date.isoformat()} to {end_date.isoformat()}",
            color="#fff",
            fontsize=14,
        )
        ax.set_xticks(x)
        ax.set_xticklabels(
            [d.strftime("%m/%d") for d in dates],
            color="#ccc",
            rotation=45,
            ha="right",
        )
        ax.tick_params(colors="#ccc")

        y_min = max(0, min(l90_vals + [0]) - 10)
        y_max = max(l10_vals + [60]) + 10
        ax.set_ylim(bottom=y_min, top=y_max)

        ax.legend(
            loc="upper right",
            facecolor="#1a1a2e",
            edgecolor="#333",
            labelcolor="#e0e0e0",
        )
        ax.grid(True, alpha=0.15, color="#fff")
        for spine in ax.spines.values():
            spine.set_color("#333")

        fig.tight_layout()
        fig.savefig(output_path, dpi=150, facecolor="#1a1a2e")
        plt.close(fig)

    # ------------------------------------------------------------------
    # Full dashboard
    # ------------------------------------------------------------------

    def generate_dashboard(self) -> None:
        """Run all generators to produce the full dashboard:
        archive page + weekly summary + monthly summary.
        """
        self.generate_archive_page()
        self.generate_weekly_summary()
        self.generate_monthly_summary()
