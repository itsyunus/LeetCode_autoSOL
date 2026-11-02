# 🧠 LeetCode Daily Auto-Solver

Fully automated system that solves your LeetCode daily challenge every day — even when you're offline, asleep, or completely disconnected. Runs on GitHub Actions with AI-powered solution generation.

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                   GitHub Actions (Daily Cron)                │
│                    Runs at 00:30 UTC daily                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Fetch daily challenge ──→ LeetCode GraphQL API           │
│  2. Check if already solved ──→ Skip if yes                  │
│  3. Check local cache ──→ Use cached solution if available   │
│  4. Generate solution ──→ Gemini AI (2.5 Flash)              │
│  5. Pre-validate ──→ Run against sample test cases           │
│  6. Submit solution ──→ LeetCode Submit API                  │
│  7. Handle failures ──→ AI refinement loop (up to 3x)       │
│  8. Cache & commit ──→ Save solution + push to repo          │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## 🚀 Setup (5 minutes)

### Step 1: Fork or Clone This Repo

```bash
# Option A: Fork on GitHub (recommended — keeps Actions enabled)
# Click "Fork" on the GitHub page

# Option B: Clone and push to your own repo
git clone <this-repo-url> leetcode-auto-solver
cd leetcode-auto-solver
git remote set-url origin https://github.com/YOUR_USERNAME/leetcode-auto-solver.git
git push -u origin main
```

### Step 2: Get Your LeetCode Session Tokens

1. Open [leetcode.com](https://leetcode.com) and **log in**
2. Open DevTools: `F12` (or `Cmd+Option+I` on Mac)
3. Go to **Application** → **Cookies** → `https://leetcode.com`
4. Find and copy these two cookies:

| Cookie Name | What It Is |
|---|---|
| `LEETCODE_SESSION` | Your auth session token (long string) |
| `csrftoken` | CSRF protection token |

> ⚠️ **These tokens expire every ~2 weeks.** Set a reminder to refresh them.

### Step 3: Get a Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click **"Create API Key"**
3. Copy the key

### Step 4: Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these three secrets:

| Secret Name | Value |
|---|---|
| `LEETCODE_SESSION` | Your LeetCode session cookie |
| `LEETCODE_CSRF_TOKEN` | Your LeetCode CSRF token |
| `GEMINI_API_KEY` | Your Gemini API key |

### Step 5: Enable GitHub Actions

1. Go to your repo → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**
3. The solver will now run automatically every day at 00:30 UTC

### Step 6 (Optional): Run It Now

- Go to **Actions** → **"🧠 LeetCode Daily Auto-Solver"** → **"Run workflow"**
- Select branch `main` and click **Run workflow**

## 📁 Project Structure

```
leetcode-auto-solver/
├── .github/workflows/
│   └── daily_solve.yml      # GitHub Actions cron workflow
├── src/
│   ├── __init__.py
│   ├── leetcode_api.py      # LeetCode GraphQL/REST API client
│   ├── solver.py            # AI solution generator (Gemini)
│   ├── solutions_db.py      # Local solutions cache
│   └── main.py              # Pipeline orchestrator
├── solutions/               # Auto-populated with accepted solutions
├── logs/                    # Daily solve logs & result JSONs
├── requirements.txt
├── .env.example             # Environment variable template
└── README.md
```

## ⚙️ Configuration

Set these as GitHub Actions variables (Settings → Variables → Actions):

| Variable | Default | Description |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Which Gemini model to use |
| `SOLUTION_LANGUAGE` | `python3` | Language for solutions |
| `DRY_RUN` | `false` | Generate without submitting |
| `SKIP_IF_SOLVED` | `true` | Skip if already solved today |

## 🔄 Token Refresh Automation

LeetCode session tokens expire. To minimize manual work:

1. **Option A (Simple):** Set a calendar reminder every 2 weeks to refresh tokens
2. **Option B (Advanced):** Use a browser extension like [Cookie AutoRefresh] to extend token life

When refreshing:
1. Log into LeetCode in your browser
2. Copy the new `LEETCODE_SESSION` and `csrftoken` values
3. Update them in GitHub Secrets

## 📊 Tracking Your Progress

Every solved problem is:
- **Saved** in the `solutions/` directory with metadata
- **Logged** in `logs/result_YYYY-MM-DD.json`
- **Committed** to git with a descriptive message like:
  ```
  ✅ [2026-11-02] #2463 Minimum Total Distance Traveled — accepted
  ```

Check your repo's commit history for a clean daily log!

## 🏃 Running Locally

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/leetcode-auto-solver.git
cd leetcode-auto-solver

# Install dependencies
pip install -r requirements.txt

# Copy env template and fill in your values
cp .env.example .env
# Edit .env with your tokens

# Source the env file and run
export $(cat .env | xargs)
python -m src.main
```

## 🛠️ Troubleshooting

| Issue | Fix |
|---|---|
| `401 Unauthorized` | Refresh your LeetCode session tokens |
| `CSRF verification failed` | Update `LEETCODE_CSRF_TOKEN` secret |
| `No submission ID returned` | Rate limited — try again in a few minutes |
| Workflow stopped running | GitHub disables crons after 60 days of inactivity. The keepalive job handles this, but check if it's still enabled |
| Wrong answer on submission | The AI refinement loop retries up to 3 times with error feedback |

## ⚠️ Disclaimer

This tool is for personal productivity and learning. Use responsibly and in accordance with LeetCode's Terms of Service.

## License

MIT

