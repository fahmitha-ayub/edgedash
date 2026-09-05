"""
mock_fetcher.py — MockFetcher agent.

Returns 12 realistic fake job listings for the configured role and city.
4 of the 12 have fixed (source, url) pairs so their IDs are stable across
every run — these are the rows used to prove deduplication.
"""
from __future__ import annotations

from typing import Any

from edgedash.agents.base import Agent, AgentResult
from edgedash import storage


# ---------------------------------------------------------------------------
# The 4 stable listings (same url + source every run → same SHA-256 id)
# ---------------------------------------------------------------------------

_STABLE: list[dict[str, Any]] = [
    {
        "title": "Data Analyst",
        "company": "Flipkart",
        "location": "Bengaluru",
        "url": "https://careers.flipkart.com/jobs/data-analyst-blr-001",
        "source": "flipkart-careers",
        "description": (
            "Join Flipkart's Analytics team. You'll own end-to-end dashboards "
            "in Tableau and Power BI, write complex SQL against Hive and "
            "Redshift, and partner with product managers on A/B test analysis. "
            "Required: Python, SQL, Tableau, 2+ years experience."
        ),
        "posted_at": "2026-08-15T09:00:00+00:00",
    },
    {
        "title": "Senior Data Analyst",
        "company": "Swiggy",
        "location": "Bengaluru",
        "url": "https://careers.swiggy.com/openings/senior-data-analyst-99",
        "source": "swiggy-careers",
        "description": (
            "Drive growth analytics for Swiggy's supply chain. Deep-dive into "
            "logistics data with Python (Pandas, NumPy), build Looker dashboards, "
            "and automate ETL pipelines. Required: SQL, Python, dbt, 4+ years."
        ),
        "posted_at": "2026-08-14T11:30:00+00:00",
    },
    {
        "title": "Data Analyst — Marketing",
        "company": "PhonePe",
        "location": "Bengaluru",
        "url": "https://phonepe.com/careers/data-analyst-marketing-042",
        "source": "phonepe-careers",
        "description": (
            "Measure and optimise PhonePe's performance marketing campaigns. "
            "Build attribution models, run cohort analyses, and present weekly "
            "insights to leadership. Stack: SQL, Python, Google Sheets, Mixpanel. "
            "2–4 years experience preferred."
        ),
        "posted_at": "2026-08-13T08:00:00+00:00",
    },
    {
        "title": "Business Intelligence Analyst",
        "company": "Razorpay",
        "location": "Bengaluru",
        "url": "https://razorpay.com/jobs/bi-analyst-blr-007",
        "source": "razorpay-careers",
        "description": (
            "Own Razorpay's self-serve BI layer. Design star-schema data models, "
            "maintain dbt pipelines, and build dashboards in Metabase. "
            "Required: SQL (PostgreSQL), dbt, Python, Power BI or Metabase. "
            "3+ years in BI/analytics."
        ),
        "posted_at": "2026-08-12T14:00:00+00:00",
    },
]

# ---------------------------------------------------------------------------
# The 8 varied listings (urls include a timestamp fragment so they are always
# treated as new — in a real fetcher these would be genuinely new posts)
# ---------------------------------------------------------------------------

_VARIED: list[dict[str, Any]] = [
    {
        "title": "Junior Data Analyst",
        "company": "Zepto",
        "location": "Bengaluru",
        "url": "https://jobs.zepto.co/data-analyst-jr-2026-08-20",
        "source": "zepto-careers",
        "description": (
            "Entry-level role on Zepto's 10-minute commerce analytics team. "
            "You'll learn the full analytics stack: SQL, Python, and Excel. "
            "Strong attention to detail required. 0–2 years experience."
        ),
        "posted_at": "2026-08-20T06:00:00+00:00",
    },
    {
        "title": "Data Analyst — Fintech",
        "company": "Groww",
        "location": "Bengaluru",
        "url": "https://groww.in/careers/data-analyst-fintech-2026-08-19",
        "source": "groww-careers",
        "description": (
            "Analyse user behaviour and product funnels for Groww's mutual fund "
            "and stock trading products. Required: SQL, Python, Amplitude or "
            "Mixpanel, Tableau. 2+ years in product analytics."
        ),
        "posted_at": "2026-08-19T10:00:00+00:00",
    },
    {
        "title": "Senior Analytics Engineer",
        "company": "Dunzo",
        "location": "Bengaluru",
        "url": "https://dunzo.com/careers/analytics-engineer-sr-2026-08-18",
        "source": "dunzo-careers",
        "description": (
            "Build and own Dunzo's analytics engineering layer. Write dbt models, "
            "manage data quality tests, and enable self-serve analytics across "
            "teams. Required: SQL, dbt, Python, Spark or BigQuery. 4–6 years."
        ),
        "posted_at": "2026-08-18T09:30:00+00:00",
    },
    {
        "title": "Data Analyst — Operations",
        "company": "Meesho",
        "location": "Bengaluru",
        "url": "https://meesho.io/jobs/data-analyst-ops-2026-08-17",
        "source": "meesho-careers",
        "description": (
            "Support Meesho's social commerce operations with data. Build "
            "dashboards in Tableau, write SQL reports, and automate repetitive "
            "Excel workflows with Python scripts. 1–3 years experience."
        ),
        "posted_at": "2026-08-17T08:00:00+00:00",
    },
    {
        "title": "Lead Data Analyst",
        "company": "CRED",
        "location": "Bengaluru",
        "url": "https://careers.cred.club/lead-data-analyst-2026-08-16",
        "source": "cred-careers",
        "description": (
            "Lead a team of 3 analysts at CRED. Own the credit-risk and rewards "
            "analytics domain. Drive experimentation frameworks and storytelling "
            "with data. Required: SQL, Python, R or Stata, 6+ years experience."
        ),
        "posted_at": "2026-08-16T11:00:00+00:00",
    },
    {
        "title": "Product Analyst",
        "company": "Nykaa",
        "location": "Bengaluru",
        "url": "https://nykaa.com/careers/product-analyst-2026-08-15",
        "source": "nykaa-careers",
        "description": (
            "Partner with Nykaa's product team to measure feature launches. "
            "Run A/B tests, analyse funnels, build dashboards in Power BI. "
            "Required: SQL, Python, Power BI, Google Analytics. 2–4 years."
        ),
        "posted_at": "2026-08-15T07:00:00+00:00",
    },
    {
        "title": "Data Analyst — Supply Chain",
        "company": "BigBasket",
        "location": "Bengaluru",
        "url": "https://bigbasket.com/careers/supply-chain-analyst-2026-08-14",
        "source": "bigbasket-careers",
        "description": (
            "Optimise BigBasket's dark-store replenishment with data. Build "
            "demand forecasting models in Python, write SQL against Redshift, "
            "and present insights in weekly ops reviews. 3+ years experience."
        ),
        "posted_at": "2026-08-14T09:00:00+00:00",
    },
    {
        "title": "Associate Data Analyst",
        "company": "upGrad",
        "location": "Bengaluru",
        "url": "https://upgrad.com/careers/associate-data-analyst-2026-08-13",
        "source": "upgrad-careers",
        "description": (
            "Support upGrad's learner success team with weekly cohort reports. "
            "Tools: SQL, Excel, Google Data Studio, some Python scripting. "
            "Fresh graduates or 0–1 year experience welcome."
        ),
        "posted_at": "2026-08-13T10:00:00+00:00",
    },
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MockFetcher:
    name: str = "mock_fetcher"

    def run(self, config: Any, storage_mod: Any, stop_conditions: dict[str, Any] | None = None) -> AgentResult:
        """Fetch 12 fake listings and write them via storage.upsert_listings.

        Args:
            config: Configuration object
            storage_mod: Storage module
            stop_conditions: Optional limits from orchestrator (ignored for mock)

        Returns AgentResult with the count of genuinely NEW rows inserted.
        The 4 stable listings will return 0 new rows on the second run,
        making deduplication directly observable in the console output.
        """
        from edgedash.storage import utc_now

        fetched_at = utc_now()

        rows: list[dict[str, Any]] = []
        for listing in _STABLE + _VARIED:
            row = dict(listing)
            row["fetched_at"] = fetched_at
            rows.append(row)

        new_count = storage_mod.upsert_listings(rows)

        notes = (
            f"Fetched {len(rows)} listings "
            f"({len(_STABLE)} stable + {len(_VARIED)} varied). "
            f"{new_count} new, {len(rows) - new_count} duplicate(s) skipped."
        )
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=new_count,
            notes=notes,
        )
