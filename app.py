"""
app.py — Job-seeker focused dashboard for EdgeDash.

Per rule 38: reads from the LAST PASSING CYCLE only (except the activity log).
Per rule 49: Never writes. Never runs a cycle. Read-only access.
Per rule 50: Robust to hostile startup - shows status messages, never crashes.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta

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
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            return (False, "Database not configured. Set DATABASE_URL environment variable.")
        
        from edgedash import storage
        storage.configure("unused_for_postgres")
        
        with storage._connection() as conn:
            pass
        
        return (True, None)
    
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
        return (False, f"Database connection failed: {str(e)}")


_init_success, _init_error = init_app()

if _init_success:
    from edgedash import storage
    from edgedash.query import ask as query_module


# ---------------------------------------------------------------------------
# Safe data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def safe_load_latest_passing_cycle():
    if not _init_success:
        return None
    try:
        return storage.get_latest_passing_cycle()
    except Exception as e:
        logger.error(f"Failed to load passing cycle: {e}")
        return None


@st.cache_data(ttl=60)
def safe_load_recent_cycles(limit: int = 30):
    if not _init_success:
        return []
    try:
        return storage.get_recent_cycles(limit)
    except Exception as e:
        logger.error(f"Failed to load recent cycles: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_top_scored_listings(limit: int = 10):
    if not _init_success:
        return []
    try:
        listings = storage.get_scored_listings(limit)
        # Enrich with extracted facts
        enriched = []
        for listing in listings:
            desc_hash = storage.make_listing_id(listing.get("source", ""), listing.get("url", ""))
            facts = storage.get_extraction(desc_hash)
            enriched.append({**listing, "facts": facts})
        return enriched
    except Exception as e:
        logger.error(f"Failed to load scored listings: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_latest_gaps():
    if not _init_success:
        return []
    try:
        return storage.get_latest_gap_snapshot()
    except Exception as e:
        logger.error(f"Failed to load gaps: {e}")
        return []


@st.cache_data(ttl=60)
def safe_load_total_counts():
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
    if not iso_str:
        return "—"
    try:
        if isinstance(iso_str, str):
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        elif hasattr(iso_str, 'strftime'):
            dt = iso_str
        else:
            return str(iso_str)
        return dt.strftime("%b %d, %Y")
    except (ValueError, AttributeError, TypeError):
        return str(iso_str) if iso_str else "—"


def days_ago(iso_str: str | None) -> str:
    """Return 'X days ago' format."""
    if not iso_str:
        return "Unknown"
    try:
        if isinstance(iso_str, str):
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        elif hasattr(iso_str, 'timestamp'):
            dt = iso_str
        else:
            return "Unknown"
        
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = now - dt
        days = delta.days
        
        if days == 0:
            return "Today"
        elif days == 1:
            return "Yesterday"
        elif days < 7:
            return f"{days} days ago"
        elif days < 30:
            return f"{days // 7} weeks ago"
        else:
            return f"{days // 30} months ago"
    except:
        return "Unknown"


def verdict_emoji(verdict: str | None) -> str:
    if verdict == "pass":
        return "✅"
    elif verdict == "fail":
        return "❌"
    elif verdict == "degraded":
        return "⚠️"
    else:
        return "❓"


# ---------------------------------------------------------------------------
# Main Dashboard Sections
# ---------------------------------------------------------------------------

def render_header():
    """Render hero section with status and next action."""
    st.title("🎯 Your Career Intelligence Dashboard")
    
    try:
        passing_cycle = safe_load_latest_passing_cycle()
        counts = safe_load_total_counts()
        
        if not passing_cycle:
            st.warning("⏳ Analyzing job market... First scan scheduled. Check back soon!")
            return
        
        # Hero metrics
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "🎯 Jobs Analyzed",
                counts["scored"],
                f"from {counts['total']} listings"
            )
        
        with col2:
            last_update = format_datetime(passing_cycle.get("finished_at"))
            st.metric("🔄 Last Updated", last_update)
        
        with col3:
            verdict = passing_cycle.get("verdict", "")
            if verdict == "pass":
                st.metric("📊 System Health", "Healthy", delta="✓")
            else:
                st.metric("📊 System Health", "Degraded", delta="!")
        
        st.divider()
    
    except Exception as e:
        logger.error(f"Header render failed: {e}")
        st.error("Unable to load status")


def render_best_matches():
    """Show top job opportunities with actionable insights."""
    st.header("💼 Your Best Job Matches")
    st.caption("Top opportunities ranked by fit score — focus your energy here")
    
    try:
        listings = safe_load_top_scored_listings(limit=10)
        
        if not listings:
            st.info("No analyzed jobs yet. The system will find matches on the next scan.")
            return
        
        for listing in listings:
            score = listing.get("fit_score", 0)
            match_pct = min(100, score)  # Cap at 100%
            
            # Color-coded match indicator
            if match_pct >= 80:
                match_color = "#28a745"  # Green
                match_label = "🎯 Excellent Match"
            elif match_pct >= 60:
                match_color = "#ffc107"  # Yellow
                match_label = "⭐ Good Match"
            else:
                match_color = "#6c757d"  # Gray
                match_label = "💡 Consider"
            
            with st.container():
                # Header row
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown(f"### {listing.get('title', 'Untitled')} at {listing.get('company', 'Unknown')}")
                
                with col2:
                    st.markdown(
                        f"<div style='text-align: right; font-size: 24px; font-weight: bold; color: {match_color};'>"
                        f"{match_pct}% {match_label}</div>",
                        unsafe_allow_html=True
                    )
                
                # Details row
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write(f"📍 **Location:** {listing.get('location', 'Not specified')}")
                
                with col2:
                    posted = days_ago(listing.get('posted_at'))
                    st.write(f"📅 **Posted:** {posted}")
                
                with col3:
                    st.write(f"🏢 **Source:** {listing.get('source', 'Unknown')}")
                
                # Why it matches
                reason = listing.get('fit_reason', '')
                if reason:
                    # Extract first part before "|" (the human-readable reason)
                    if "|" in reason:
                        display_reason = reason.split("|")[0].strip()
                    else:
                        display_reason = reason
                    st.write(f"**Why this matches:** {display_reason}")
                
                # Skills analysis
                facts = listing.get('facts', {})
                if facts:
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        required = facts.get('required_skills', [])
                        if required:
                            st.write("✅ **Required skills:**")
                            st.write(", ".join(required[:5]))  # Show first 5
                    
                    with col2:
                        nice_to_have = facts.get('nice_to_have', [])
                        if nice_to_have:
                            st.write("💎 **Nice to have:**")
                            st.write(", ".join(nice_to_have[:5]))
                
                # Action buttons
                col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
                
                with col1:
                    url = listing.get('url', '')
                    if url:
                        st.link_button("🔗 View Job", url, use_container_width=True)
                
                with col2:
                    if url:
                        st.link_button("📤 Apply", url, use_container_width=True)
                
                st.markdown("---")
        
    except Exception as e:
        logger.error(f"Best matches render failed: {e}")
        st.error("Unable to load job matches")


def render_skill_recommendations():
    """Show skill gaps as career development recommendations."""
    st.header("🎓 Skills to Focus On")
    st.caption("Learn these skills to unlock more opportunities")
    
    try:
        gaps = safe_load_latest_gaps()
        
        if not gaps:
            st.info("No skill analysis yet. Run a cycle to see recommendations.")
            return
        
        # Show top 10 gaps
        for i, gap in enumerate(gaps[:10], 1):
            skill = gap.get('skill', 'Unknown')
            cost = gap.get('opportunity_cost', 0)
            blocked_count = gap.get('listings_blocked', 0)
            
            # Priority level
            if cost >= 50:
                priority = "🔥 High Priority"
                priority_color = "#dc3545"
            elif cost >= 30:
                priority = "⚡ Medium Priority"
                priority_color = "#ffc107"
            else:
                priority = "💡 Nice to Have"
                priority_color = "#6c757d"
            
            with st.container():
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown(f"### {i}. {skill.title()}")
                
                with col2:
                    st.markdown(
                        f"<div style='text-align: right; font-size: 18px; font-weight: bold; color: {priority_color};'>"
                        f"{priority}</div>",
                        unsafe_allow_html=True
                    )
                
                # Impact metrics
                col1, col2 = st.columns(2)
                
                with col1:
                    st.metric("🎯 Jobs Requiring This", blocked_count)
                
                with col2:
                    st.metric("💰 Impact Score", f"{cost:.0f}/100")
                
                # Why it matters
                if blocked_count > 0:
                    st.write(f"**Why learn this:** {blocked_count} job{'s' if blocked_count != 1 else ''} in your match list require{'' if blocked_count != 1 else 's'} this skill. Adding it could significantly boost your match scores.")
                
                st.markdown("---")
        
    except Exception as e:
        logger.error(f"Skill recommendations render failed: {e}")
        st.error("Unable to load skill recommendations")


def render_next_steps():
    """Show clear action plan."""
    st.header("✨ What Should I Do Next?")
    
    try:
        listings = safe_load_top_scored_listings(limit=3)
        gaps = safe_load_latest_gaps()
        
        if listings:
            st.subheader("🎯 Immediate Actions")
            st.write("**Apply to these top matches today:**")
            for i, job in enumerate(listings[:3], 1):
                title = job.get('title', 'Untitled')
                company = job.get('company', 'Unknown')
                score = job.get('fit_score', 0)
                url = job.get('url', '')
                st.write(f"{i}. [{title} at {company}]({url}) — {score}% match")
        
        if gaps:
            st.subheader("📚 This Week")
            top_gap = gaps[0]
            skill = top_gap.get('skill', 'Unknown')
            blocked = top_gap.get('listings_blocked', 0)
            st.write(f"**Start learning {skill.title()}** — it's required for {blocked} jobs in your matches.")
        
        st.subheader("📅 Coming Up")
        st.write("• Next job scan: Daily at 6:00 AM IST")
        st.write("• Check back daily for new matches")
        st.write("• Update your profile in config.yaml to refine matches")
        
    except Exception as e:
        logger.error(f"Next steps render failed: {e}")
        st.error("Unable to load action plan")


def render_ask_your_data():
    """Interactive Q&A about your job search data."""
    st.header("💬 Ask Your Data")
    st.caption("Ask questions about your job search in plain English")
    
    try:
        # Example questions as buttons
        st.write("**Try asking:**")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("Which companies are hiring?", key="q1"):
                st.session_state.question = "Which companies are hiring?"
        
        with col2:
            if st.button("What are my top 5 matches?", key="q2"):
                st.session_state.question = "What are my top 5 matches?"
        
        with col3:
            if st.button("What skills should I learn?", key="q3"):
                st.session_state.question = "What skills should I learn?"
        
        # Question input
        question = st.text_input(
            "Your question:",
            value=st.session_state.get("question", ""),
            placeholder="e.g., How many Python jobs are there?",
            key="user_question"
        )
        
        if question:
            with st.spinner("Thinking..."):
                try:
                    answer = query_module.ask(question)
                    
                    # Display answer
                    st.write("**Answer:**")
                    st.write(answer.text)
                    
                    # Display underlying data
                    if answer.rows:
                        with st.expander("📊 See the data"):
                            st.dataframe(answer.rows, use_container_width=True)
                
                except Exception as e:
                    logger.error(f"Query failed: {e}")
                    st.error(f"Sorry, I couldn't answer that. Error: {e}")
    
    except Exception as e:
        logger.error(f"Ask section render failed: {e}")
        st.error("Q&A temporarily unavailable")


def render_system_health():
    """Show agent health in human terms."""
    st.header("🔧 System Health")
    
    try:
        cycles = safe_load_recent_cycles(limit=30)
        
        if not cycles:
            st.info("No activity yet.")
            return
        
        st.caption(f"Last {len(cycles)} job scans")
        
        # Health summary
        pass_count = sum(1 for c in cycles if c.get("verdict") == "pass")
        success_rate = (pass_count / len(cycles) * 100) if cycles else 0
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("✅ Successful", pass_count)
        with col2:
            fail_count = sum(1 for c in cycles if c.get("verdict") == "fail")
            st.metric("❌ Failed", fail_count)
        with col3:
            degraded_count = sum(1 for c in cycles if c.get("verdict") == "degraded")
            st.metric("⚠️ Partial", degraded_count)
        with col4:
            st.metric("📊 Success Rate", f"{success_rate:.0f}%")
        
        # Activity log
        rows = []
        for cycle in cycles:
            verdict = cycle.get("verdict", "unknown")
            
            # Translate technical notes to human language
            notes = cycle.get("notes", "")
            summary = ""
            
            if "fetcher" in notes.lower():
                if "skip" not in notes.lower():
                    summary = "✓ Scanned job boards"
                else:
                    summary = "⏭ Skipped scan (recent data)"
            
            if "scorer" in notes.lower():
                if "skip" not in notes.lower():
                    if summary:
                        summary += " • ✓ Analyzed matches"
                    else:
                        summary = "✓ Analyzed matches"
                else:
                    if summary:
                        summary += " • ⏭ No new jobs to score"
            
            if "gap" in notes.lower():
                if "skip" not in notes.lower():
                    if summary:
                        summary += " • ✓ Updated skill recommendations"
                    else:
                        summary = "✓ Updated skill recommendations"
            
            # Extract failure reason if any
            failure = ""
            if verdict != "pass":
                if "gap_sample_size" in notes:
                    failure = "Not enough data to verify"
                elif "spread" in notes:
                    failure = "Score distribution issue"
                elif "freshness" in notes:
                    failure = "Data too old"
                else:
                    failure = "Quality check failed"
            
            # Status with color
            if verdict == "pass":
                status = f'<span style="color: #28a745; font-weight: bold;">✅ Success</span>'
            elif verdict == "fail":
                status = f'<span style="color: #dc3545; font-weight: bold;">❌ Failed</span>'
            elif verdict == "degraded":
                status = f'<span style="color: #ffc107; font-weight: bold;">⚠️ Partial</span>'
            else:
                status = f'<span style="color: #6c757d;">❓ Unknown</span>'
            
            rows.append({
                "Time": format_datetime(cycle.get("started_at")),
                "Status": status,
                "What Happened": summary if summary else "—",
                "Issue": failure if failure else "—",
            })
        
        # Display as HTML for colored status
        import pandas as pd
        df = pd.DataFrame(rows)
        
        st.markdown(
            df.to_html(escape=False, index=False),
            unsafe_allow_html=True
        )
        
    except Exception as e:
        logger.error(f"System health render failed: {e}")
        st.error("Unable to load system health")


def render_footer():
    """Footer with last update and repo link."""
    st.divider()
    try:
        passing_cycle = safe_load_latest_passing_cycle()
        if passing_cycle:
            last_update = format_datetime(passing_cycle.get("finished_at"))
            st.caption(f"Last verified update: {last_update} • [EdgeDash on GitHub](https://github.com/yourusername/edgedash)")
        else:
            st.caption("[EdgeDash on GitHub](https://github.com/yourusername/edgedash)")
    except Exception as e:
        logger.error(f"Footer render failed: {e}")
        st.caption("[EdgeDash on GitHub](https://github.com/yourusername/edgedash)")


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="EdgeDash — Career Intelligence",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    
    # Check init status
    if not _init_success:
        st.error(f"⚠️ System Error: {_init_error}")
        st.stop()
    
    # Render dashboard sections in order
    render_header()
    render_next_steps()
    render_best_matches()
    render_skill_recommendations()
    render_ask_your_data()
    render_system_health()
    render_footer()


if __name__ == "__main__":
    main()
