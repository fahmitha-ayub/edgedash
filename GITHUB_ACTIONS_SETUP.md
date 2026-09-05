# GitHub Actions Setup Guide

## Scheduled Orchestrator Execution

The EdgeDash orchestrator runs automatically every day at **06:00 IST (India Standard Time)** via GitHub Actions.

### Schedule Details

- **IST Time**: 06:00 (6:00 AM India)
- **UTC Time**: 00:30 (12:30 AM UTC)
- **Cron**: `30 0 * * *`
- **Frequency**: Daily

> **Note**: IST = UTC+5:30, so 06:00 IST = 00:30 UTC

---

## Required Secrets

You must add these secrets to your GitHub repository:

### 1. Add DATABASE_URL

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `DATABASE_URL`
5. Value: Your Supabase Postgres connection string
   ```
   postgresql://postgres.[project-ref]:[password]@aws-0-region.pooler.supabase.com:6543/postgres
   ```
6. Click **Add secret**

### 2. Add GEMINI_API_KEY (Optional)

1. Same steps as above
2. Name: `GEMINI_API_KEY`
3. Value: Your Google Gemini API key
4. Click **Add secret**

---

## Manual Triggering (Test Now)

You can trigger the workflow manually without waiting for the scheduled time:

### Option 1: GitHub Web UI

1. Go to your repository on GitHub
2. Click **Actions** tab
3. Click **EdgeDash Orchestrator Cycle** in the left sidebar
4. Click **Run workflow** button (top right)
5. Click the green **Run workflow** button in the dropdown
6. Wait for the workflow to complete (shows up in the list below)

### Option 2: GitHub CLI

```bash
# Install GitHub CLI if not already installed
# https://cli.github.com/

# Authenticate (first time only)
gh auth login

# Trigger the workflow
gh workflow run cycle.yml

# View the run status
gh run list --workflow=cycle.yml

# View logs of the latest run
gh run view --log
```

### Option 3: Using API

```bash
# Replace [owner], [repo], and [token]
curl -X POST \
  -H "Accept: application/vnd.github.v3+json" \
  -H "Authorization: token [YOUR_GITHUB_TOKEN]" \
  https://api.github.com/repos/[owner]/[repo]/actions/workflows/cycle.yml/dispatches \
  -d '{"ref":"main"}'
```

---

## Workflow Features

### Per Rule 51: Hard Timeout
- ✅ Job timeout: 10 minutes maximum
- ✅ Prevents runaway processes
- ✅ Stays within free tier limits

### Per Rule 48: No Secret Leaks
- ✅ Secrets passed as environment variables only
- ✅ No secrets in logs or output
- ✅ Connection strings sanitized in output
- ✅ Failed steps cannot expose secrets

### Per Rule 36: No Automatic Retries
- ✅ Workflow does NOT retry on failure
- ✅ Orchestrator handles retries internally (max 1)
- ✅ Failures trigger GitHub notification
- ✅ You review and fix issues manually

### Artifacts
- ✅ Cycle logs uploaded after every run
- ✅ Available even if cycle fails
- ✅ Retained for 30 days
- ✅ Download from Actions → Run → Artifacts

---

## Monitoring

### View Workflow Runs

1. Go to **Actions** tab in your repository
2. Click **EdgeDash Orchestrator Cycle**
3. See all runs (scheduled and manual)
4. Click any run to see details

### Check Logs

1. Click on a workflow run
2. Click **run-cycle** job
3. Expand any step to see detailed logs
4. Download artifacts to see cycle logs

### Email Notifications

GitHub sends email notifications for:
- ✅ Workflow failures
- ✅ Workflow success (if you enable in GitHub settings)
- ⚠️ First failure only (not repeated)

To enable success notifications:
1. GitHub profile → **Settings**
2. **Notifications** → **Actions**
3. Enable **Send notifications for workflow runs**

---

## Troubleshooting

### "Secret DATABASE_URL not found"

**Cause**: Secret not added to GitHub repository  
**Fix**: Add DATABASE_URL secret in Settings → Secrets → Actions

### "Connection failed"

**Cause**: Invalid DATABASE_URL or database unreachable  
**Fix**: 
1. Verify connection string format
2. Test locally: `python -m edgedash.storage --check`
3. Check Supabase is not paused (free tier auto-pauses after inactivity)

### "Timeout after 10 minutes"

**Cause**: Orchestrator took too long  
**Fix**:
1. Check orchestrator logs (artifact)
2. Verify LLM API is responding
3. Check `llm_batch_size` in config.yaml (reduce if needed)

### "No artifact uploaded"

**Cause**: Orchestrator didn't create log files  
**Fix**: This is normal if logging isn't implemented yet - workflow succeeds without artifacts

---

## Cost Estimate

### GitHub Actions Free Tier
- **2,000 minutes/month** for private repos
- **Unlimited** for public repos
- This workflow uses ~2-5 minutes per run
- Daily runs = ~30-150 minutes/month
- **Well within free tier** ✅

### Supabase Free Tier
- Database active during workflow run
- Auto-pauses after inactivity
- Daily runs keep database active
- **Fits free tier limits** ✅

---

## Security Checklist ✅

- [x] Secrets stored in GitHub Secrets (encrypted)
- [x] Secrets passed as environment variables only
- [x] No secrets echoed in logs
- [x] Connection string sanitized in output
- [x] Workflow file committed to repo (safe - no secrets in YAML)
- [x] Failed steps don't expose secrets
- [x] Artifacts don't contain secrets

---

## Next Steps

1. **Add secrets** to GitHub repository (see above)
2. **Test manually** using "Run workflow" button
3. **Check artifacts** to see cycle logs
4. **Wait for scheduled run** at 06:00 IST tomorrow
5. **Monitor email** for failure notifications

---

## Example Output

When workflow succeeds, you'll see:

```
Run python -m edgedash.storage --migrate
Running migrations...
[storage] Using Postgres: aws-0-us-west-1.pooler.supabase.com:6543/postgres
✓ Migrations complete (postgres backend)

Run python run_cycle.py
[storage] Using Postgres: aws-0-us-west-1.pooler.supabase.com:6543/postgres
Orchestrator starting...
✓ Cycle complete
```

**No secrets visible** - only sanitized connection info (host:port/database).

---

## Workflow Runs

The workflow runs in these scenarios:

1. **Scheduled**: Every day at 00:30 UTC (06:00 IST)
2. **Manual**: When you click "Run workflow"
3. **NOT on push**: Doesn't run automatically on git push
4. **NOT on retry**: Never retries automatically

This ensures controlled execution and prevents accidental cost spikes.
