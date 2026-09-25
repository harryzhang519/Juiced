# 🎯 EV Edge — Sports Betting Analytics Dashboard

> **Real-time positive expected value (+EV) betting analysis across major sportsbooks, powered by [The-Odds-API](https://the-odds-api.com).**

EV Edge deviggs FanDuel vs DraftKings lines using the **proportional no-vig method**, identifies cross-book mispricing, and surfaces your best bets ranked by EV% — updated automatically every day.

---

## ✨ Features

| Feature | Detail |
|---|---|
| 📊 **Live Odds** | Fetches from The-Odds-API v4 (FanDuel + DraftKings) |
| 🧮 **Devigging** | Proportional no-vig method — exact fair probability extraction |
| ⚡ **Cross-Book EV** | Uses each book's line as benchmark to find the other's mispricing |
| 🏆 **Top 15+ Bets** | Ranked by EV%, graded A+ → C, filterable by market/book/EV% |
| 🎰 **Parlays** | Auto-generated 3-leg parlays with combined EV calculation |
| 🔄 **Auto Refresh** | APScheduler refreshes all sports daily (configurable cron) |
| 📱 **Responsive** | Works on desktop and mobile |
| 🎭 **Demo Mode** | Works out-of-the-box with mock MLB data — no API key needed to test |

## 🏈 Sports Covered

`MLB` · `NFL` · `NBA` · `NHL` · `NCAAF` · `NCAAB` · `EPL` · `MLS` · `MMA` · `Tennis`

---

## 🚀 Quick Start

### 1. Clone & install
```bash
git clone https://github.com/yourname/ev-edge.git
cd ev-edge
pip install -r requirements.txt
```

### 2. Configure environment
```bash
# Copy the template
cp .env.example .env

# Edit .env and add your Odds API key (optional — runs in demo mode without it)
# Get a free key at https://the-odds-api.com (500 req/month free)
ODDS_API_KEY=your_key_here
```

### 3. Run
```bash
python run.py
```

Then open **http://localhost:5000** in your browser. 🎉

---

## 🔑 The-Odds-API Setup

1. Sign up at **[https://the-odds-api.com](https://the-odds-api.com)**
2. Copy your API key
3. Add it to your `.env` file: `ODDS_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
4. Restart the app — live mode activates automatically

**Free tier:** 500 requests/month. With daily refresh across 10 sports = ~300 req/month → fits free tier.

| Plan | Requests/Month | Cost |
|---|---|---|
| Free | 500 | $0 |
| Starter | 10,000 | ~$79/mo |
| Pro | 100,000 | ~$249/mo |

---

## ⚙️ Configuration

All settings are in `.env`:

| Variable | Default | Description |
|---|---|---|
| `ODDS_API_KEY` | *(blank)* | Your The-Odds-API key |
| `FLASK_HOST` | `0.0.0.0` | Server bind address |
| `FLASK_PORT` | `5000` | Server port |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |
| `CACHE_TTL_HOURS` | `6` | Hours before cache is considered stale |
| `REFRESH_CRON` | `0 9 * * *` | Cron schedule for daily refresh (9 AM daily) |
| `SECRET_KEY` | *(change me)* | Flask session secret (change for production!) |

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web dashboard |
| `GET` | `/api/sports` | List of tracked sports |
| `GET` | `/api/ev-bets?sport=baseball_mlb` | Top +EV bets |
| `GET` | `/api/parlays?sport=baseball_mlb` | Best parlays |
| `GET` | `/api/summary?sport=baseball_mlb` | Aggregate stats |
| `POST` | `/api/refresh?sport=baseball_mlb` | Trigger fresh odds pull |
| `GET` | `/api/status` | Scheduler + API quota status |

### Query Parameters for `/api/ev-bets`

| Param | Type | Default | Description |
|---|---|---|---|
| `sport` | string | `baseball_mlb` | Sport key from `/api/sports` |
| `limit` | int | `50` | Max bets to return |
| `min_ev` | float | `0.0` | Minimum EV (e.g. `0.02` for 2%+) |
| `market` | string | `all` | `h2h` \| `spreads` \| `totals` \| `all` |
| `book` | string | `all` | `fanduel` \| `draftkings` \| `all` |

---

## 📐 Methodology

### Proportional No-Vig Devigging

```
1. Convert American odds to implied probability:
   - Favorite (-X):  P = X / (X + 100)
   - Underdog (+Y):  P = 100 / (Y + 100)

2. Sum both implied probs:
   Overround = P_a + P_b  (always > 1.0, e.g. 1.042 = 4.2% vig)

3. Divide each by sum → fair probability:
   FairP_a = P_a / Overround
   FairP_b = P_b / Overround

4. Use Book A's line to find Book B's fair price, then calculate EV:
   EV% = (FairP_a × DecimalOdds_B) − 1

5. Positive EV% → Book B is pricing Team A above fair value.
```

### Parlay Construction

- Max **1 leg per game** (independence requirement — no correlated legs)
- All legs must be from the **same sportsbook** (realistic to place)
- Auto-greedy selection: highest EV bets first, 1 per unique game
- Combined EV = (Product of fair probs × Product of decimal odds) − 1

---

## 🗂️ Project Structure

```
ev-edge/
├── run.py                    ← Entry point: start server + scheduler
├── config.py                 ← All configuration (env-based)
├── requirements.txt
├── .env.example              ← Copy to .env and fill in your key
├── .gitignore
├── backend/
│   ├── api_client.py         ← The-Odds-API wrapper + caching + demo fallback
│   ├── devig.py              ← Core EV math: devig, EV%, parlay builder
│   ├── scheduler.py          ← APScheduler: daily refresh + manual trigger
│   └── server.py             ← Flask app: REST API routes
├── frontend/
│   ├── index.html            ← Single-page dashboard
│   ├── style.css             ← Dark glassmorphism design
│   └── app.js                ← Fetch → render: tabs, table, parlays, status
└── data/
    ├── mock_baseball_mlb.json  ← Demo data (committed)
    └── *.json                  ← Live cache (git-ignored, auto-generated)
```

---

## 🚢 Deployment

### Render (Free Tier)
```yaml
# render.yaml
services:
  - type: web
    name: ev-edge
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python run.py
    envVars:
      - key: ODDS_API_KEY
        sync: false
      - key: SECRET_KEY
        generateValue: true
```

### Heroku
```bash
# Procfile
web: python run.py
```
```bash
heroku create ev-edge
heroku config:set ODDS_API_KEY=your_key
git push heroku main
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "run.py"]
```

---

## 🗺️ Roadmap / SaaS Upgrade Path

- [ ] **User auth** — login/signup, subscription tiers
- [ ] **Email/SMS alerts** — notify on high-EV bets (>5%)
- [ ] **Historical tracking** — record past bets, track win rate vs EV prediction
- [ ] **More bookmakers** — BetMGM, Caesars, PointsBet as additional benchmarks
- [ ] **NRFI/Player props** — via alternate markets API endpoint
- [ ] **Odds movement tracker** — show line movement direction (sharp vs public)
- [ ] **Bet slip** — save and share your chosen bets

---

## ⚠️ Disclaimer

This tool is for **informational and educational purposes only**. Positive EV is a long-run statistical concept — it does not guarantee short-term profit. Always verify odds on the sportsbook app before placing any wager. Gambling involves real financial risk. Bet responsibly. 21+ only.

---

*Built with ❤️ using Python, Flask, The-Odds-API, and Vanilla JS.*
