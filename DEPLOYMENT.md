# EdgeDash Deployment Guide

## Deploying to Streamlit Community Cloud

### Prerequisites

1. **GitHub Repository**: Push your code to GitHub
2. **Supabase Account**: Create a free Postgres database at [supabase.com](https://supabase.com)
3. **Gemini API Key** (optional): For natural language queries

### Step 1: Set up Supabase Database

1. Create a new Supabase project
2. Go to Settings → Database
3. Copy the **Connection string** (URI format)
4. Run migrations to create tables:

```bash
# Set DATABASE_URL locally
export DATABASE_URL="postgresql://postgres.[ref]:[password]@host:6543/postgres"

# Run migrations
python -m edgedash.storage --migrate

# Verify
python -m edgedash.storage --check
```

### Step 2: Deploy to Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io/)
2. Click "New app"
3. Select your GitHub repository
4. Set main file path: `app.py`
5. Click "Advanced settings"

### Step 3: Configure Secrets

In the Streamlit Cloud dashboard, add these secrets:

```toml
# Required
DATABASE_URL = "postgresql://postgres.[ref]:[password]@host:6543/postgres"

# Optional (for natural language queries)
GEMINI_API_KEY = "your-api-key"
```

### Step 4: Deploy!

Click "Deploy" and wait for the app to start.

## Environment Variables

The app requires these environment variables:

- **DATABASE_URL** (required): Postgres connection string
  - Format: `postgresql://user:password@host:port/database`
  - Supabase format: `postgresql://postgres.[ref]:[password]@aws-0-region.pooler.supabase.com:6543/postgres`

- **GEMINI_API_KEY** (optional): Google Gemini API key
  - Required only for the "Ask your data" feature
  - Get it from [https://makersuite.google.com/app/apikey](https://makersuite.google.com/app/apikey)

## Security Notes

- ✅ No secrets are ever logged or displayed to users
- ✅ Database connection strings are never shown
- ✅ All errors show user-friendly messages (never stack traces)
- ✅ The dashboard is read-only (cannot modify data)

## Scheduled Jobs

The dashboard only displays data. To populate it, you need to run the orchestrator periodically:

**Option 1: GitHub Actions** (recommended for free tier)
```yaml
name: Run EdgeDash Orchestrator

on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python run_orchestrator.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

**Option 2: Heroku Scheduler** (if using Heroku)
**Option 3: Render Cron Jobs** (if using Render)

## Troubleshooting

**"Database not configured"**
- Check that DATABASE_URL is set in Streamlit secrets
- Verify the connection string format
- Ensure your IP is allowed in Supabase (Settings → Database → Connection pooling)

**"No cycles yet"**
- This is normal on first deploy
- Run the orchestrator manually or wait for the scheduled job

**Empty charts**
- Tables exist but have no data
- Run: `python run_orchestrator.py` locally to populate

## Monitoring

Check the Streamlit Cloud logs for:
- Database connection status on startup
- Any errors (logged server-side, never shown to users)
- Query performance

## Cost Estimates

- **Streamlit Community Cloud**: Free (public apps only)
- **Supabase Free Tier**: 500MB database, 2GB bandwidth
- **Gemini API Free Tier**: 60 requests/minute

All components fit within free tiers for personal use.
