import os, sys, json
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()
from google import genai
import backend.pikkit as pk

bets = pk._load()
settled = [b for b in bets if b.get('result') in ('win', 'loss', 'push')]
wins = sum(1 for b in settled if b['result'] == 'win')
losses = sum(1 for b in settled if b['result'] == 'loss')
total_pnl = sum(b.get('pnl') or 0 for b in settled)

bet_sample = [{
    'date': b.get('date'),
    'sport': b.get('sport'),
    'book': b.get('sportsbook'),
    'market': b.get('market'),
    'selection': (b.get('selection') or '')[:45],
    'odds': b.get('odds'),
    'stake': b.get('stake'),
    'pnl': b.get('pnl'),
    'result': b.get('result')
} for b in settled[-40:]]

prompt = f"""You are an elite quantitative sports betting analyst for EV Edge.
Analyze this verified betting performance ledger according to the +EV quantitative framework.

Record: {wins}W-{losses}L | Total Net Profit: ${total_pnl:+.2f} | Win Rate: {wins/len(settled)*100:.1f}%
Recent sample of settled wagers:
{json.dumps(bet_sample, indent=2)}

Analysis Framework:
1. Closing Line Value (CLV) & Market Mispricing vs. Standard Sports Variance:
   Evaluate whether losses were driven by natural sports variance (underdog swings, 1-run games) vs structural leakage (negative-EV multi-leg parlays, unhedged high-vig wagers).
2. Quant Patterns:
   Highlight 3 deep quantitative patterns across sport selection (MLB, Soccer, Tennis), market types (Straight Moneylines vs Multi-leg Parlays), and sportsbooks.
3. Actionable Strategic Recommendations:
   Give 3 precise recommendations to protect bankroll, eliminate negative-EV drag, and optimize return on capital.
4. Model & Performance Scoring:
   Assign a performance score from 1 to 100 and label ('Elite', 'Strong', 'Solid', 'Developing', 'Needs Work'). Given ${total_pnl:+.2f} net profit and +225% ROI, score should reflect strong overall profitability while objectively noting parlay variance exposure.

Respond strictly in valid JSON format with keys:
"summary": string,
"score": int,
"score_label": string,
"patterns": list of strings,
"recommendations": list of strings,
"model_notes": string
"""

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
resp = client.models.generate_content(model='gemini-3.5-flash-lite', contents=prompt)
print(resp.text.strip())
