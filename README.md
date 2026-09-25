# 🧃 Juiced — Intelligent Sports Betting Ledger & AI Analytics

> **Automated bet tracking, visual bankroll intelligence, and Gemini AI-powered slip extraction & quant diagnostics.**

**Juiced** eliminates manual betting spreadsheets and brings institutional-grade tracking to your action. Drop or paste any bet slip screenshot to auto-log your wagers, visualize your long-term equity curve and daily P&L heatmap, and run AI-driven quantitative diagnostics on your betting patterns.

---

## 📖 Table of Contents

- [The Betting Ledger](#-the-betting-ledger)
- [Gemini AI Engine](#-gemini-ai-engine)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [API Overview](#-api-overview)
- [Tech Stack](#-tech-stack)

---

## 📒 The Betting Ledger

The **Juiced Ledger** is an all-in-one portfolio tracker designed specifically for sports bettors across all major bookmakers (FanDuel, DraftKings, BetMGM, Caesars, Betway, and more).

### Key Ledger Capabilities:
* **Zero-Friction Bet Ingestion**:
  * **Instant Screenshot Import**: Press `Ctrl+V` / `⌘V` anywhere in the dashboard or drag-and-drop bet slip images.
  * **Manual Logging**: Fast manual modal for cash bets, in-person books, or custom wagers.
* **Core Performance Metrics**:
  * **Net Profit / Loss (P&L)**: Real-time calculation of net gains or losses across all settled bets.
  * **Return on Investment (ROI %)**: True yield calculated as `Net PnL / Total Staked`.
  * **Total Volume Tracked**: Complete visibility into cumulative amount wagered and total returns.
  * **Win Rate & Average Odds**: Detailed distribution of your betting lines and hit rates.
* **Visual Bankroll Curve**:
  * Interactive cumulative equity chart tracking your bankroll trajectory over time.
  * Real-time drawdown and upswing visualization.
* **Daily P&L Calendar Heatmap**:
  * Month-by-month calendar view displaying daily profit and loss intensity.
  * Color-coded performance density (big wins, small wins, break-even, small losses, big losses) with total monthly summaries.
* **Multi-Dimensional Breakdown Analytics**:
  * **By Sportsbook**: Compare profitability, volume, and ROI across different books to see where your edge is highest.
  * **By Sport & Market**: Filter performance across leagues (NFL, MLB, NBA, NHL, WNBA, Soccer, Tennis, MMA) and bet types (Moneylines, Spreads, Totals, Player Props, Parlays).
* **Comprehensive Bet History**:
  * Search, filter, inspect original slip screenshots, and manage historical wagers in a searchable table.

---

## 🧠 Gemini AI Engine

Juiced integrates Google's latest multimodal Gemini models (`gemini-3.5-flash-lite`, `gemini-3.5-flash`, and `gemini-3.8-flash`) to automate data ingestion and deliver quantitative coaching.

### 1. Multimodal Slip Auto-Parsing (Gemini Vision)
Forget typing out bet details manually. Juiced feeds your uploaded slip screenshots directly into Gemini Vision:
* **Automated Field Extraction**:
  * Event date & time
  * Sportsbook name (FanDuel, DraftKings, BetMGM, etc.)
  * Sport & League
  * Game / Matchup
  * Bet Selection (team, player, prop line)
  * Market Category (Moneyline, Spread, Over/Under, Player Prop, Parlay)
  * American Odds (e.g., `-110`, `+175`)
  * Stake & Potential Payout
  * Bet Status (`win`, `loss`, `push`, `pending`) and computed P&L
* **Multi-Leg & Multi-Slip Support**:
  * Accurately parses complex multi-leg parlays, describing all legs within the selection.
  * Detects and separates multiple slips captured in a single screenshot.

### 2. Quant Pattern Diagnosis & Leak Detection
The AI doesn't just record your bets—it analyzes your decision-making:
* **Bettor Performance Rating (1–100)**:
  * Generates an objective algorithmic score and ranking (`Elite`, `Strong`, `Solid`, `Developing`, or `Needs Work`) based on profit quality, volume, and odds distribution.
* **Deep Pattern Identification**:
  * Detects behavioral biases (e.g., heavy chalk bias, over-reliance on high-variance longshots, or parlay drag).
  * Evaluates market selection efficiency (identifies sports or markets where you consistently leak EV).
* **Variance vs. Mispricing Assessment**:
  * Distinguishes between lucky run-outs and sustainable positive expected value (+EV) execution.
* **Strategic Quantitative Recommendations**:
  * Delivers targeted, actionable recommendations to tighten staking, optimize market allocation, and improve bankroll growth.

---

## 🚀 Quick Start

### 1. Prerequisites
* Python 3.10+
* A free Gemini API key from [Google AI Studio](https://aistudio.google.com/)

### 2. Clone & Install
```bash
git clone https://github.com/harryzhang519/Juiced.git
cd Juiced
pip install -r requirements.txt
```

### 3. Setup Environment
Copy the example environment configuration:
```bash
cp .env.example .env
```
Edit `.env` with your key:
```env
# Gemini API Key (Required for slip screenshot parsing & AI diagnosis)
GEMINI_API_KEY=your_gemini_api_key_here
```

### 4. Launch the App
```bash
python run.py
```
Open **`http://localhost:5000`** in your browser.

---

## ⚙️ Configuration

Key settings available in `.env`:

| Key | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(blank)* | Google Gemini API key for screenshot Vision & AI diagnosis |
| `FLASK_HOST` | `0.0.0.0` | Host interface |
| `FLASK_PORT` | `5000` | Port number |

---

## 📡 API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/pikkit/bets` | Retrieve all tracked bets with status & P&L |
| `POST` | `/api/pikkit/bets` | Manually log a single bet |
| `DELETE` | `/api/pikkit/bets/<id>` | Delete a specific bet record |
| `POST` | `/api/pikkit/upload` | Upload slip screenshot for Gemini Vision auto-parsing |
| `GET` | `/api/pikkit/stats` | Aggregate metrics (ROI%, Net PnL, Sportsbook breakdown) |
| `GET` | `/api/pikkit/calendar` | Daily P&L calendar matrix and monthly summaries |
| `GET` | `/api/pikkit/ai-eval` | Run Gemini AI quantitative diagnostics on bet history |

---

## 🛠️ Tech Stack

* **Backend**: Python, Flask
* **AI & Vision**: Google Gemini Models (`gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash`) via `google-genai`
* **Frontend**: Vanilla JS, Chart.js, HTML5, CSS3 Glassmorphism
* **Analytics**: Financial P&L modeling, ROI & equity curve calculations
