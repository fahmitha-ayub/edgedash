# GitHub Actions Setup - Summary

## ✅ Workflow Created

**File**: `.github/workflows/cycle.yml`

### Schedule
- **Your time**: 06:00 IST (India Standard Time) daily
- **UTC time**: 00:30 UTC (midnight thirty)
- **Cron**: `30 0 * * *`

### Features
- ✅ Runs migrations first (safe to repeat)
- ✅ Runs orchestrator cycle
- ✅ 10-minute hard timeout (rule 51)
- ✅ Uploads cycle logs as artifacts
- ✅ Manual trigger available
- ✅ No automatic retries (rule 36)

---

## 🔑 Required Secrets

Add these in **GitHub repo → Settings → Secrets → Actions**:

### 1. DATABASE_URL (Required)
```
postgresql://postgres.[project-ref]:[password]@aws-0-region.pooler.supabase.com:6543/postgres
```

### 2. GEMINI_API_KEY (Optional)
```
your-gemini-api-key-here
```

**⚠️ These are the ONLY secrets you need to add**

---

## 🧪 Test Manually Right Now

### Quick Test (Web UI)

1. Go to https://github.com/[your-username]/[your-repo]/actions
2. Click **"EdgeDash Orchestrator Cycle"** in left sidebar
3. Click **"Run workflow"** button (top right, green)
4. Select branch: `main`
5. Click **"Run workflow"** in dropdown
6. Refresh page - see run appear in list
7. Click on the run to see live logs

### CLI Test (if you have `gh` installed)

```bash
# Navigate to your repo
cd c:\Users\farzi\Desktop\edgedash

# Trigger workflow
gh workflow run cycle.yml

# View status
gh run list --workflow=cycle.yml --limit 1

# View logs (most recent run)
gh run view --log
```

---

## 🔒 Security Audit Results

### Rule 48: No Secret Leaks ✅

**Verified safe:**
- ✅ Secrets passed as environment variables only
- ✅ No `echo $DATABASE_URL` or similar in steps
- ✅ Connection strings sanitized: shows only `host:port/database`
- ✅ No secrets in workflow file itself
- ✅ Failed commands cannot expose secrets

**Grep results:**
```bash
✅ No print(DATABASE_URL) in code
✅ No print(GEMINI_API_KEY) in code
✅ No print(config) that could leak secrets
✅ Only safe print: _db_url.split('@')[-1]
```

**Example safe output:**
```
[storage] Using Postgres: aws-0-region.pooler.supabase.com:6543/postgres
```
(No username or password visible)

---

## 🚫 Rule 36: No Auto-Retry ✅

**Workflow behavior:**
- ✅ Does NOT retry on failure
- ✅ Fails immediately and visibly
- ✅ Sends GitHub notification
- ✅ Requires manual investigation

**Why no retry:**
- Orchestrator already handles retries internally (max 1)
- Workflow retry would multiply the retry count
- Better to fix issues than mask them with retries

---

## 📊 What Happens on Each Run

1. **Checkout code** from GitHub
2. **Set up Python 3.11** with pip cache
3. **Install dependencies** from requirements.txt
4. **Run migrations** (creates tables if missing)
5. **Run orchestrator** (fetch → score → analyze → verify)
6. **Upload logs** as artifact (even if failed)

**Duration**: ~2-5 minutes per run  
**Cost**: Free (within GitHub Actions free tier)

---

## 📁 Artifacts

After each run:
- Logs uploaded as `cycle-log-[run-number]`
- Retained for 30 days
- Download from: Actions → Run → Artifacts section
- Available even if run fails

---

## 🔔 Notifications

GitHub sends email for:
- ❌ Workflow failures
- ✅ First failure (not repeated)
- ⚠️ Success emails optional (Settings → Notifications)

**You will be notified immediately if a cycle fails.**

---

## 📅 Scheduled Runs

Starting tomorrow, workflow runs automatically at:
- **00:30 UTC** = **06:00 IST** daily

**Manual runs available anytime** via "Run workflow" button.

---

## ✅ Deployment Checklist

Before you commit and push:

- [x] Workflow file created: `.github/workflows/cycle.yml`
- [x] Secrets documented: DATABASE_URL, GEMINI_API_KEY
- [x] Schedule correct: 00:30 UTC = 06:00 IST
- [x] Timeout set: 10 minutes
- [x] No secret leaks verified
- [x] No auto-retry (by design)
- [x] Manual trigger enabled
- [x] .gitignore excludes .env but includes .github/

---

## 🚀 Next Steps

1. **Commit workflow**:
   ```bash
   git add .github/workflows/cycle.yml
   git commit -m "Add scheduled orchestrator workflow"
   git push
   ```

2. **Add secrets** on GitHub:
   - Settings → Secrets → Actions → New repository secret
   - Add DATABASE_URL
   - Add GEMINI_API_KEY (optional)

3. **Test manually**:
   - Actions → EdgeDash Orchestrator Cycle → Run workflow

4. **Check results**:
   - View logs in Actions tab
   - Download artifacts to see cycle details
   - Verify database populated

5. **Wait for scheduled run**:
   - First automatic run: tomorrow at 06:00 IST
   - Check email for success/failure notification

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Secret not found" | Add DATABASE_URL in repo Settings → Secrets |
| "Connection failed" | Verify DATABASE_URL format, test with --check |
| "Timeout" | Check LLM API, reduce batch_size in config.yaml |
| "No artifacts" | Normal if no logs created, workflow still succeeds |
| "Workflow not listed" | Push .github/workflows/cycle.yml to GitHub |

---

## 📖 Full Documentation

See **GITHUB_ACTIONS_SETUP.md** for:
- Detailed secret setup instructions
- All manual trigger methods
- Monitoring guide
- Cost estimates
- Security checklist

---

**✅ All rules satisfied:**
- Rule 36: No automatic retries
- Rule 48: No secret leaks
- Rule 49: Scheduler separate from dashboard
- Rule 51: 10-minute timeout, stays in free tier

**Ready to deploy!** 🚀
