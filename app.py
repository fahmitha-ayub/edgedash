"""
app.py — Read-only Streamlit dashboard for EdgeDash.

Per rule 38: reads from the LAST PASSING CYCLE only (except the activity log).
Per rule 49: Never writes. Never runs a cycle. Read-only access.
Per rule 50: Robust to hostile startup - shows status messages, never crashes.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

import streamlit as st

# Configure logging (server-side only, never shown to user)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Robust initialization (rule 50)
# ---------------------------------------------------------------------------

def init_app():
    """Initialize app with robust error handling. Returns (success, error_message)."""
    try:
        # Check DATABASE_URL
        if not os.environ.get("DATABASE_URL"):
            return False, "DATABASE_URL not configured. Please set it in Streamlit secrets."
        
        # Try to import and configure storage
        try:
            from edgedash import storage
            from edgedash.config import load_config
        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            return False, f"Failed to load application modules: {type(e).__name__}"
        
        # Try to configure storage
        try:
            config = load_config()
            storage.configure(config.db_path)
        except Exception as e:
            logger.error(f"Configuration failed: {e}", exc_info=True)
            return False, f"Configuration error: {type(e).__name__}"
        
        # Test database connection
        try:
            with storage._connection() as conn:
                pass  # Just test connection
        except Exception as e:
            logger.error(f"Database connection failed: {e}", exc_info=True)
            return False, "Database connection failed. Check DATABASE_URL and network access."
        
        return True, None
        
    except Exception as e:
        logger.error(f"Unexpected init error: {e}", exc_info=True)
        return False, f"Unexpected initialization error: {type(e).__name__}"


# Initialize once
_init_success, _init_error = init_app()

if _init_success:
    from edgedash import storage
    from edgedash.config import load_config
    from edgedash.query.ask import ask


# ---------------------------------------------------------------------------
# Safe data loading with fallbacks (rule 50)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def safe_load_latest_passing_cycle():
    """Get the last verified cycle metadata. Returns None on error."""
    if not _init_success:
        return None
    try:
        return storage.get_latest_passing_cycle()
    except Exception as e:
        logger.error(f"Failed to load passing cycle: {e}")
        return None


@st.cache_data(ttl=60)
def safe_load_recent_cycles(limit: int = 30):
    """Get recent cycles for activity log. Returns empty list on error."""
    if not _init_success:
        return []
    try:
        return storage.get_recent_cycles(limit)
    except Exception as e:
        logger.error(f"Failed to load recent cycles: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_top_scored_listings(limit: int = 10):
    """Get top-scored listings. Returns empty list on error."""
    if not _init_success:
        return []
    try:
        return storage.get_scored_listings(limit)
    except Exception as e:
        logger.error(f"Failed to load scored listings: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_latest_gaps():
    """Get latest skill gaps. Returns empty list on error."""
    if not _init_success:
        return []
    try:
        return storage.get_latest_gap_snapshot()
    except Exception as e:
        logger.error(f"Failed to load gaps: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_total_counts():
    """Get total listing counts. Returns zeros on error."""
    if not _init_success:
        return {"total": 0, "scored": 0}
    try:
        with storage._connection() as conn:
            row = storage._fetchone(conn, """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) as scored
                FROM listings
            """)
        return row if row else {"total": 0, "scored": 0}
    except Exception as e:
        logger.error(f"Failed to load counts: {e}")
        return {"total": 0, "scored": 0}


# ---------------------------------------------------------------------------
# Formatting Helpers
# ---------------------------------------------------------------------------

def format_datetime(iso_str: str | None) -> str:
    """Format ISO datetime to readable string."""
    if not iso_str:
        return "—"
    try:
        # Handle both string (SQLite) and datetime object (Postgres)
        if isinstance(iso_str, str):
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        elif hasattr(iso_str, 'strftime'):
            # Already a datetime object
            dt = iso_str
        else:
            return str(iso_str)
        
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError, TypeError):
        return str(iso_str) if iso_str else "—"


def format_duration(started: str | None, finished: str | None) -> str:
    """Calculate duration between two ISO timestamps."""
    if not started or not finished:
        return "—"
    try:
        # Handle both string (SQLite) and datetime object (Postgres)
        if isinstance(started, str):
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        elif hasattr(started, 'timestamp'):
            start_dt = started
        else:
            return "—"
        
        if isinstance(finished, str):
            end_dt = datetime.fromisoformat(finished.replace("Z", "+00:00"))
        elif hasattr(finished, 'timestamp'):
            end_dt = finished
        else:
            return "—"
        
        duration = (end_dt - start_dt).total_seconds()
        if duration < 60:
            return f"{duration:.1f}s"
        return f"{duration / 60:.1f}m"
    except (ValueError, AttributeError, TypeError):
        return "—"


def verdict_emoji(verdict: str | None) -> str:
    """Return emoji for verdict status."""
    if verdict == "pass":
        return "✅"
    elif verdict in ("fail", "degraded"):
        return "❌"
    return "⚪"


# ---------------------------------------------------------------------------
# Dashboard Sections (all wrapped for safety)
# ---------------------------------------------------------------------------

def render_header():
    """Render header with last verified cycle status."""
    st.title("EdgeDash — Career Intelligence Agent")
    
    try:
        passing_cycle = safe_load_latest_passing_cycle()
        counts = safe_load_total_counts()
        all_cycles = safe_load_recent_cycles(limit=1)
        
        if not passing_cycle:
            st.warning("⚠️ No verified cycles yet. Waiting for first orchestrator run.")
            return
        
        # Check if newest cycle is passing
        newest_cycle = all_cycles[0] if all_cycles else None
        is_stale = (
            newest_cycle 
            and newest_cycle.get("verdict") != "pass"
            and newest_cycle.get("id") != passing_cycle.get("id")
        )
        
        if is_stale:
            st.error(
                f"⚠️ **Latest cycle failed verification.** "
                f"Data below is from an earlier verified cycle: "
                f"{format_datetime(passing_cycle['finished_at'])}"
            )
        
        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Last Verified Cycle",
                format_datetime(passing_cycle.get("finished_at")),
            )
        
        with col2:
            st.metric("Total Listings", counts["total"])
        
        with col3:
            st.metric("Scored Listings", counts["scored"])
        
        with col4:
            verdict_status = "✅ PASS" if passing_cycle.get("verdict") == "pass" else "❌ FAIL"
            st.metric("Current Status", verdict_status)
        
        st.divider()
    
    except Exception as e:
        logger.error(f"Header render failed: {e}")
        st.error("Unable to load cycle status")


def render_activity_log():
    """Render recent cycle activity log (main panel)."""
    st.header("🔄 Agent Activity Log")
    
    try:
        cycles = safe_load_recent_cycles(limit=30)
        
        if not cycles:
            st.info("💤 No cycles recorded yet. Run the orchestrator to populate data.")
            return
        
        # Show count and summary
        st.caption(f"Showing {len(cycles)} most recent cycles")
        
        # Build compact table data
        rows = []
        for cycle in cycles:
            verdict = cycle.get("verdict", "unknown")
            status_icon = verdict_emoji(verdict)
            
            # Extract duration
            duration = format_duration(cycle.get("started_at"), cycle.get("finished_at"))
            
            # Extract agent summary from notes
            notes = cycle.get("notes", "")
            agents_run = []
            agents_skipped = []
            
            if notes:
                # Simple parsing - look for agent names
                if "fetcher" in notes.lower():
                    if "skip" in notes.lower() and "fetcher" in notes.lower():
                        agents_skipped.append("fetcher")
                    else:
                        agents_run.append("fetcher")
                if "scorer" in notes.lower():
                    if "skip" in notes.lower() and "scorer" in notes.lower():
                        agents_skipped.append("scorer")
                    else:
                        agents_run.append("scorer")
                if "gap_analyzer" in notes.lower() or "gap" in notes.lower():
                    if "skip" in notes.lower():
                        agents_skipped.append("gaps")
                    else:
                        agents_run.append("gaps")
            
            # Compact summary
            if agents_run:
                summary = " + ".join(agents_run)
            else:
                summary = "—"
            
            if agents_skipped:
                summary += f" (⏭ {', '.join(agents_skipped)})"
            
            # Extract key failure reason if any
            failed_reason = "—"
            if verdict != "pass":
                failed_checks = cycle.get("failed_checks", "")
                if failed_checks:
                    # Extract first failure reason
                    if "," in failed_checks:
                        failed_reason = failed_checks.split(",")[0].strip()
                    else:
                        failed_reason = failed_checks
            
            rows.append({
                "": status_icon,
                "Time": format_datetime(cycle.get("started_at")),
                "Agents": summary,
                "Verdict": verdict.upper() if verdict else "—",
                "Failure": failed_reason,
                "Duration": duration,
            })
        
        # Display as styled dataframe
        import pandas as pd
        df = pd.DataFrame(rows)
        
        # Apply conditional formatting based on verdict
        def highlight_verdict(row):
            if row["Verdict"] == "PASS":
                return ['background-color: #d4edda'] * len(row)
            elif row["Verdict"] == "FAIL":
                return ['background-color: #f8d7da'] * len(row)
            elif row["Verdict"] == "DEGRADED":
                return ['background-color: #fff3cd'] * len(row)
            else:
                return [''] * len(row)
        
        styled_df = df.style.apply(highlight_verdict, axis=1)
        
        st.dataframe(
            styled_df,
            use_container_width=True,
            height=min(400 + (len(cycles) * 10), 650),  # Dynamic height
            hide_index=True,
            column_config={
                "": st.column_config.TextColumn(width="small"),
                "Time": st.column_config.TextColumn(width="medium"),
                "Agents": st.column_config.TextColumn(width="large"),
                "Verdict": st.column_config.TextColumn(width="small"),
                "Failure": st.column_config.TextColumn(width="medium"),
                "Duration": st.column_config.TextColumn(width="small"),
            }
        )
        
        # Add summary metrics in columns
        col1, col2, col3, col4 = st.columns(4)
        
        pass_count = sum(1 for c in cycles if c.get("verdict") == "pass")
        fail_count = sum(1 for c in cycles if c.get("verdict") == "fail")
        degraded_count = sum(1 for c in cycles if c.get("verdict") == "degraded")
        
        with col1:
            st.metric("✅ Passed", pass_count)
        with col2:
            st.metric("❌ Failed", fail_count)
        with col3:
            st.metric("⚠️ Degraded", degraded_count)
        with col4:
            success_rate = (pass_count / len(cycles) * 100) if cycles else 0
            st.metric("Success Rate", f"{success_rate:.0f}%")
        
        # Expandable recent failures
        recent_failures = [c for c in cycles[:10] if c.get("verdict") != "pass"]
        if recent_failures:
            st.markdown("### 🔍 Recent Failures")
            for cycle in recent_failures[:3]:  # Show up to 3
                verdict = cycle.get("verdict", "unknown")
                timestamp = format_datetime(cycle.get("started_at"))
                
                with st.expander(f"{verdict_emoji(verdict)} {timestamp} - {verdict.upper()}"):
                    st.code(cycle.get("notes", "No notes"), language="text")
    
    except Exception as e:
        logger.error(f"Activity log render failed: {e}")
        st.error("Unable to load activity log")
                
        if cycle.get("failed_checks"):
            st.text(f"\nFailed checks:\n{cycle.get('failed_checks')}")
        
        st.text(f"\nRecords touched: {cycle.get('records_touched', 0)}")
        st.text(f"Retry count: {cycle.get('retry_count', 0)}")
        st.text(f"Duration: {format_duration(cycle.get('started_at'), cycle.get('finished_at'))}")
    
    except Exception as e:
        logger.error(f"Activity log render failed: {e}")
        st.error("Unable to load activity log")


def render_ask_section():
    """Render natural language query section (rules 42-45)."""
    st.header("💬 Ask Your Data")
    st.caption("Ask questions about job listings in plain English")
    
    try:
        if not _init_success:
            st.warning("Database not configured. Cannot answer questions.")
            return
        
        config = load_config()
        
        # Example questions as clickable buttons
        st.write("**Try these examples:**")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("Which companies are hiring?", use_container_width=True):
                st.session_state["query"] = "Which companies are hiring?"
        
        with col2:
            if st.button("Show me top 5 matches", use_container_width=True):
                st.session_state["query"] = "Show me top 5 matches"
        
        with col3:
            if st.button("What skills should I learn?", use_container_width=True):
                st.session_state["query"] = "What skills should I learn?"
        
        # Text input
        question = st.text_input(
            "Or ask your own question:",
            value=st.session_state.get("query", ""),
            placeholder="e.g., Which companies posted jobs in the last 3 days?",
            key="question_input",
        )
        
        # Clear session state after displaying
        if "query" in st.session_state:
            del st.session_state["query"]
        
        if question:
            with st.spinner("Thinking..."):
                try:
                    answer = ask(question, config)
                    
                    # Display answer
                    st.markdown("### Answer")
                    st.write(answer.text)
                    
                    # Display metadata
                    if answer.tool_used:
                        st.caption(f"📊 Tool used: `{answer.tool_used}` with params: `{answer.params}`")
                    
                    # Display underlying data
                    if answer.rows:
                        st.markdown("### Underlying Data")
                        st.dataframe(answer.rows, use_container_width=True, hide_index=True)
                        st.caption(f"{len(answer.rows)} rows returned")
                    
                except Exception as e:
                    logger.error(f"Query failed: {e}")
                    st.error("Unable to answer question. Please try again later.")
    
    except Exception as e:
        logger.error(f"Ask section render failed: {e}")
        st.error("Unable to load query interface")


def render_top_listings():
    """Render top scored listings (compact panel)."""
    st.subheader("Top 10 Scored Listings")
    
    try:
        listings = safe_load_top_scored_listings(limit=10)
        
        if not listings:
            st.info("No scored listings yet.")
            return
        
        rows = []
        for listing in listings[:10]:
            reason = listing.get("fit_reason", "")
            if len(reason) > 60:
                reason = reason[:57] + "..."
            
            rows.append({
                "Score": listing.get("fit_score", 0),
                "Title": listing.get("title", ""),
                "Company": listing.get("company", ""),
                "Reason": reason,
            })
        
        st.dataframe(rows, use_container_width=True, hide_index=True)
    
    except Exception as e:
        logger.error(f"Top listings render failed: {e}")
        st.error("Unable to load top listings")


def render_skill_gaps():
    """Render current top skill gaps (compact panel)."""
    st.subheader("Top 10 Skill Gaps")
    
    try:
        gaps = safe_load_latest_gaps()
        
        if not gaps:
            st.info("No skill gap analysis yet.")
            return
        
        rows = []
        for gap in gaps[:10]:
            rows.append({
                "Skill": gap.get("skill", ""),
                "Listings Blocked": gap.get("listings_blocked", 0),
                "Opportunity Cost": f"{gap.get('opportunity_cost', 0):.2f}",
                "Mean Score": f"{gap.get('mean_score', 0):.1f}",
                "Top Score": gap.get("top_score", 0),
            })
        
        st.dataframe(rows, use_container_width=True, hide_index=True)
    
    except Exception as e:
        logger.error(f"Skill gaps render failed: {e}")
        st.error("Unable to load skill gaps")


def render_footer():
    """Render footer with last cycle timestamp and GitHub link."""
    try:
        st.divider()
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            passing_cycle = safe_load_latest_passing_cycle()
            if passing_cycle:
                timestamp = format_datetime(passing_cycle.get("finished_at"))
                st.caption(f"Last successful cycle: {timestamp}")
            else:
                st.caption("Waiting for first cycle...")
        
        with col2:
            st.caption("🔗 [GitHub Repository](https://github.com/yourusername/edgedash)")
    
    except Exception as e:
        logger.error(f"Footer render failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="EdgeDash",
        page_icon="📊",
        layout="wide",
    )
    
    # Check initialization
    if not _init_success:
        st.error(f"⚠️ Application initialization failed")
        st.write(_init_error)
        st.info(
            "**Required configuration:**\n\n"
            "Set the following in Streamlit secrets:\n"
            "- `DATABASE_URL`: Postgres connection string\n"
            "- `GEMINI_API_KEY`: Google Gemini API key (optional, for queries)"
        )
        st.stop()
    
    # Render sections (each wrapped for safety)
    render_header()
    render_activity_log()
    
    st.divider()
    
    render_ask_section()
    
    st.divider()
    
    # Bottom row: two columns
    col1, col2 = st.columns(2)
    
    with col1:
        render_top_listings()
    
    with col2:
        render_skill_gaps()
    
    render_footer()


if __name__ == "__main__":
    main()
