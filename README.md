# EdgeDash

> Autonomous AI Career Intelligence Agent - Let AI find your next job while you sleep

EdgeDash is an automated job search assistant that runs on autopilot. It scans job boards daily, scores every listing against your profile, identifies skill gaps, and presents insights through a clean web dashboard. Set it up once, check it daily for your best matches.

[![Deploy to Streamlit](https://edgedash-keve7spuxjnweqkhla236n.streamlit.app/)

## What It Does

- **Scans job boards automatically** - No manual searching
- **Scores every job for YOU** - Based on your skills, preferences, and career goals
- **Identifies skill gaps** - Shows exactly which skills would unlock more opportunities
- **Answers your questions** - Ask "Which companies are hiring?" in plain English
- **Runs on autopilot** - Scheduled daily via GitHub Actions

## Quick Start

### Prerequisites

- Python 3.11+
- A Supabase account (free tier works)
- A Google Gemini API key (free tier works)
- A GitHub account (for scheduling)

### 1. Clone and Install

```bash
git clone https://github.com/yourusername/edgedash.git
cd edgedash
pip install -r requirements.txt
```

### 2. Configure Your Profile

Edit `config.yaml` with your information:

```yaml
profile:
  target_city: "Berlin"              # Your preferred city
  target_role: "Software Engineer"    # Your target role
  target_seniority: "mid"            # junior/mid/senior
  keywords:                          # Keywords to filter jobs
    - "Python"
    - "Backend"
    - "API"

skills:
  my_skills:                         # Your current skills
    - "Python"
    - "JavaScript"
    - "PostgreSQL"
    - "Docker"
  
  skill_aliases:                     # Normalize skill names
    js: "JavaScript"
    postgres: "PostgreSQL"

sources:                             # Which job boards to scan
  - arbeitnow

scoring_weights:                     # Customize what matters to YOU
  required_skill: 20                 # Points per required skill matched
  nice_to_have_skill: 5
  seniority_match: 15
  remote_ok: 10                      # Boost for remote jobs
  keyword_match: 3

verification:
  max_data_age_days: 3               # How old data can be
  min_score_count: 3                 # Minimum jobs to analyze
  min_gap_sample: 3                  # Minimum jobs for gap analysis
```

### 3. Set Up Database

**Option A: Supabase (Recommended)**

1. Create a free account at [supabase.com](https://supabase.com)
2. Create a new project
3. Go to Settings → Database → Connection String
4. Copy the connection string (URI format)

**Option B: Local Postgres**

```bash
# Create database
createdb edgedash

# Get connection string
postgresql://user:password@localhost:5432/edgedash
```

### 4. Get API Keys

**Gemini API (Free):**
1. Go to [ai.google.dev](https://ai.google.dev)
2. Click "Get API Key"
3. Create a new API key
4. Copy it

### 5. Configure Environment

Create `.env` file in project root:

```bash
# Required: Database connection
DATABASE_URL=postgresql://user:password@host:5432/database

# Required: LLM API for scoring and queries
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: Override defaults
# MAX_PAGES=5
# FETCH_INTERVAL_HOURS=12
```

**Important:** Never commit `.env` to git! It's already in `.gitignore`.

### 6. Initialize Database

```bash
# Create all tables
python -m edgedash.storage --migrate

# Verify connection and tables
python -m edgedash.storage --check
```

You should see:
```
Backend: postgres
Connected: ✓
Tables:
  listings: 0 rows
  extraction_cache: 0 rows
  gap_snapshots: 0 rows
  cycle_log: 0 rows
  query_log: 0 rows
```

### 7. Run First Cycle

```bash
# Run the orchestrator manually
python run_cycle.py
```

This will:
1. Fetch jobs from configured sources
2. Score them against your profile
3. Analyze skill gaps
4. Verify output quality
5. Log everything

Expected output:
```
[storage] Using Postgres: ...
EXECUTION PLAN
==================================================
fetcher       : RUN  · fetch new job listings
scorer        : RUN  · score unscored listings
gap_analyzer  : RUN  · analyze skill gaps
[RUN] fetcher: fetch new job listings
  [arbeitnow] page 1: 175 listings, 62 keyword-matched
  ...
  → ok · arbeitnow: 42 rows (42 new)
[RUN] scorer: score unscored listings
  → ok · scored 25 · range 42-89 · mean 67
[RUN] gap_analyzer: analyze skill gaps
  → ok · 10 gaps · top: Docker (5 listings, cost 0.8)
[RUN] verifier: judge output plausibility
  → ok · VERDICT: pass
Cycle complete: pass · 45.2s
```

### 8. View Dashboard Locally

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Deploy to Production

### Automated Scheduling (GitHub Actions)

1. **Push code to GitHub:**
   ```bash
   git add .
   git commit -m "Initial setup"
   git push origin main
   ```

2. **Add secrets to repository:**
   - Go to your repo → Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Add two secrets:
     - Name: `DATABASE_URL`, Value: Your Postgres connection string
     - Name: `GEMINI_API_KEY`, Value: Your Gemini API key

3. **Enable GitHub Actions:**
   - Go to Actions tab
   - Click "I understand my workflows, go ahead and enable them"

4. **Verify workflow:**
   - The workflow `.github/workflows/cycle.yml` is already configured
   - Runs daily at 06:00 IST (00:30 UTC)
   - Can be triggered manually: Actions → EdgeDash Orchestrator Cycle → Run workflow

5. **Monitor execution:**
   - Go to Actions tab after first run
   - Click on the workflow run to see logs
   - Download cycle log artifact to see detailed output

### Deploy Dashboard (Streamlit Cloud)

1. **Push to GitHub** (if not already done)

2. **Go to [share.streamlit.io](https://share.streamlit.io)**

3. **Click "New app"**

4. **Configure:**
   - Repository: `yourusername/edgedash`
   - Branch: `main`
   - Main file path: `app.py`

5. **Add secrets:**
   - Click "Advanced settings"
   - In Secrets section, add:
     ```toml
     DATABASE_URL = "postgresql://user:password@host:5432/database"
     ```

6. **Deploy:**
   - Click "Deploy"
   - Wait 2-3 minutes
   - Your dashboard is now live!

## Usage

### Daily Workflow

1. **Morning:** Open your dashboard
2. **Check:** "What Should I Do Next?" section
3. **Apply:** To top 3 recommended jobs
4. **Learn:** Start on the top priority skill
5. **Ask:** Questions about your job market

### Example Questions

The dashboard has a natural language interface. Try asking:

- "Which companies are hiring?"
- "Show me my top 5 matches"
- "What skills should I learn?"
- "How many Python jobs are there?"
- "Tell me about remote opportunities"
- "What's the trend for Docker?"

### Manual Cycle Trigger

**Via GitHub Actions:**
1. Go to Actions tab
2. Select "EdgeDash Orchestrator Cycle"
3. Click "Run workflow"
4. Select branch (main)
5. Click "Run workflow"

**Via Command Line (Local):**
```bash
python run_cycle.py
```

### Monitoring

**Check cycle health:**
- Dashboard → System Health section (bottom)
- Shows success rate and recent activity

**View detailed logs:**
- GitHub Actions → Workflow runs → Download artifact
- Contains full cycle output

**Check database directly:**
```bash
python -m edgedash.storage --check
```

## Configuration Reference

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | Postgres connection string | `postgresql://user:pass@host:5432/db` |
| `GEMINI_API_KEY` | Yes | Google Gemini API key | `AIza...` |
| `MAX_PAGES` | No | Max pages per source (default: 5) | `10` |
| `FETCH_INTERVAL_HOURS` | No | Hours between fetches (default: 12) | `24` |

### config.yaml Sections

**profile:** Your job search criteria
- `target_city`: String (e.g., "Berlin")
- `target_role`: String (e.g., "Software Engineer")
- `target_seniority`: "junior" | "mid" | "senior"
- `keywords`: List of strings (for filtering)

**skills:** Your skill set
- `my_skills`: List of your current skills
- `skill_aliases`: Map alternate names to canonical names

**sources:** Job boards to scan
- List of source names (currently: `arbeitnow`)

**scoring_weights:** Customize scoring
- `required_skill`: Points per required skill matched
- `nice_to_have_skill`: Points per nice-to-have matched
- `seniority_match`: Points for seniority alignment
- `remote_ok`: Points for remote jobs
- `keyword_match`: Points per keyword match

**verification:** Quality thresholds
- `max_data_age_days`: Maximum data staleness
- `min_score_count`: Minimum scored jobs
- `min_gap_sample`: Minimum jobs for gap analysis

### Customizing Scoring

Want to prioritize remote jobs?
```yaml
scoring_weights:
  remote_ok: 25  # Increased from 10
```

Don't care about seniority?
```yaml
scoring_weights:
  seniority_match: 0  # Disabled
```

Boost keyword matches?
```yaml
scoring_weights:
  keyword_match: 10  # Increased from 3
```

## Troubleshooting

### "No cycles recorded yet"
**Cause:** First cycle hasn't run  
**Fix:** Run `python run_cycle.py` manually

### "Database not configured"
**Cause:** Missing `DATABASE_URL`  
**Fix:** Add to `.env` (local) or Streamlit secrets (deployed)

### "Scorer failed: API quota exceeded"
**Cause:** Hit Gemini free tier limit (20 requests/day)  
**Fix:**
- Reduce batch size in config: `max_items: 10`
- Wait until tomorrow
- Or upgrade to paid tier

### "Query timeout"
**Cause:** Gemini API slow on free tier  
**Fix:** Wait 30-60 seconds, it will complete

### "No verified cycles yet"
**Cause:** All cycles failed quality checks  
**Fix:**
1. Check System Health in dashboard for error details
2. Common issues:
   - Too few jobs found (adjust keywords)
   - Sample size too small (wait for more cycles)
   - Data staleness (check network/API keys)

### Dashboard shows old data
**Cause:** Latest cycle failed verification  
**Fix:** Dashboard shows last PASSING cycle (intentional). Check System Health for current cycle status.

### GitHub Actions workflow not running
**Cause:** Workflow disabled or secrets missing  
**Fix:**
1. Check Actions tab is enabled
2. Verify secrets are set (Settings → Secrets)
3. Check workflow file exists: `.github/workflows/cycle.yml`

## Project Structure

```
edgedash/
├── edgedash/
│   ├── agents/           # Worker agents
│   │   ├── fetcher.py    # Job listing fetcher
│   │   ├── scorer.py     # Fit score calculator
│   │   └── gap_analyzer.py  # Skill gap identifier
│   ├── sources/          # Job board integrations
│   │   ├── base.py       # Source interface
│   │   └── arbeitnow.py  # Arbeitnow.com source
│   ├── query/            # Natural language interface
│   │   ├── ask.py        # Query pipeline
│   │   └── tools.py      # Query tool registry
│   ├── config.py         # Config loader
│   ├── extractor.py      # LLM fact extraction
│   ├── llm.py            # LLM client wrapper
│   ├── orchestrator.py   # Main controller
│   ├── scoring.py        # Scoring logic
│   ├── skills.py         # Skill canonicalization
│   ├── state.py          # System state reader
│   ├── storage.py        # Database abstraction
│   └── verification.py   # Output verifier
├── .github/
│   └── workflows/
│       └── cycle.yml     # Scheduled execution
├── .streamlit/
│   └── config.toml       # Dashboard theme
├── app.py                # Dashboard interface
├── config.yaml           # Your profile & settings
├── run_cycle.py          # Orchestrator entry point
└── requirements.txt      # Python dependencies
```

## Architecture Overview

```
┌─────────────────────────────────┐
│     GitHub Actions              │
│  (Runs daily at 06:00 IST)     │
└────────────┬────────────────────┘
             │
             ▼
      ┌─────────────┐
      │Orchestrator │
      └──────┬──────┘
             │
   ┌─────────┼─────────┐
   ▼         ▼         ▼
┌────────┐┌────────┐┌──────────┐
│Fetcher ││ Scorer ││   Gap    │
│        ││        ││ Analyzer │
└────┬───┘└────┬───┘└────┬─────┘
     │         │         │
     └─────────┼─────────┘
               ▼
        ┌─────────────┐
        │  Verifier   │
        └──────┬──────┘
               │
               ▼
        ┌─────────────┐
        │ PostgreSQL  │
        │  (Supabase) │
        └──────┬──────┘
               │ (read-only)
               ▼
        ┌─────────────┐
        │  Dashboard  │
        │ (Streamlit) │
        └─────────────┘
```

## Key Features

### Autonomous Operation
- Scheduled daily execution
- No manual intervention required
- Automatic retries on transient failures
- Graceful degradation on persistent issues

### Intelligent Scoring
- Two-phase: LLM extracts facts → Code computes score
- Deterministic and reproducible
- Customizable weights
- Caching to minimize API calls

### Quality Assurance
- Every cycle verified before approval
- Multiple plausibility checks
- Dashboard only shows verified data
- Detailed failure logging

### Natural Language Queries
- No text-to-SQL (security)
- Pre-built tool registry
- Transparent data display
- Question logging for improvement

### Dual-Backend Support
- SQLite for local development
- PostgreSQL for production
- Automatic detection
- Zero code changes to switch

## API Costs (Free Tier)

**Gemini (Google):**
- Free: 20 requests/day
- EdgeDash usage: ~2 per job + 2 per question
- Sustainable at ~10 jobs/day on free tier
- Paid: $0.001/request after free tier

**Supabase:**
- Free: 500MB database
- EdgeDash usage: ~50-500KB per cycle
- Will last years on free tier

**GitHub Actions:**
- Free: 2000 min/month (private repos)
- EdgeDash usage: ~5 min/day = 150 min/month
- Well within free tier

**Streamlit Cloud:**
- Free: 1 app
- EdgeDash: Read-only, very light
- No cost concerns

## Contributing

Contributions welcome! Areas for improvement:

- **New job sources:** Add integrations for LinkedIn, Indeed, etc.
- **Query tools:** Add new analysis capabilities
- **Scoring components:** Additional fit factors
- **Dashboard features:** Charts, trends, export
- **Documentation:** Tutorials, videos, examples

See `PROJECT_SUMMARY.md` for detailed architecture docs.

## License

MIT License - see LICENSE file for details.

## Support

- **Issues:** GitHub Issues tab
- **Discussions:** GitHub Discussions
- **Documentation:** See `PROJECT_SUMMARY.md` for detailed internals

## Acknowledgments

Built with:
- [Streamlit](https://streamlit.io) - Dashboard framework
- [Google Gemini](https://ai.google.dev) - LLM for extraction
- [Supabase](https://supabase.com) - Hosted Postgres
- [GitHub Actions](https://github.com/features/actions) - Scheduling

## Roadmap

- [ ] Email notifications for high-match jobs
- [ ] More job sources (LinkedIn, Indeed)
- [ ] Salary tracking and analysis
- [ ] Application tracking
- [ ] Resume tailoring suggestions
- [ ] Interview prep based on gaps
- [ ] Mobile-responsive dashboard
- [ ] Slack/Discord bot interface

---

**Start your autonomous job search today!**

⭐ Star this repo if you find it useful!
