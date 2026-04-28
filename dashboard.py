"""
Read-only FastAPI dashboard over SQLite (portfolio, positions, transactions).

Run (same host as the bot; bind localhost behind SSH tunnel for safety):

    uvicorn dashboard:app --host 0.0.0.0 --port 8000

Tunnel from laptop:

    ssh -L 8000:localhost:8000 user@YOUR_VM

Then open http://localhost:8000
"""

import aiosqlite
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from db import DB_PATH

app = FastAPI(title="Hermes Dashboard", docs_url=None, redoc_url=None)


async def fetch_all(query: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(query, params)
        return [dict(r) for r in rows]


@app.get("/api/portfolio")
async def portfolio_api():
    portfolio_rows = await fetch_all("SELECT * FROM portfolio")
    open_positions = await fetch_all(
        """
        SELECT *
        FROM positions
        WHERE closed_at IS NULL
        ORDER BY opened_at DESC
        """
    )
    recent_transactions = await fetch_all(
        """
        SELECT *
        FROM transactions
        ORDER BY created_at DESC
        LIMIT 50
        """
    )

    return {
        "portfolio": portfolio_rows[0] if portfolio_rows else None,
        "open_positions": open_positions,
        "recent_transactions": recent_transactions,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Hermes Dashboard</title>
      <style>
        body { font-family: system-ui, Arial, sans-serif; margin: 24px; color: #222; }
        table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
        th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; }
        th { background: #f4f4f4; text-align: left; }
        .card { padding: 16px; border: 1px solid #ddd; margin-bottom: 20px; border-radius: 6px; }
        h1 { margin-top: 0; }
      </style>
    </head>
    <body>
      <h1>Hermes Dashboard</h1>
      <p style="color:#666;font-size:13px;">Read-only · Refreshes every 30s</p>
      <div id="app">Loading…</div>

      <script>
        function escapeHtml(s) {
          if (s === null || s === undefined) return '';
          return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        }

        async function load() {
          const res = await fetch('/api/portfolio');
          const data = await res.json();

          const p = data.portfolio;
          let html = '';

          if (!p) {
            html += '<div class="card"><h2>Portfolio</h2><p>No portfolio row in DB yet.</p></div>';
          } else {
            html += `
            <div class="card">
              <h2>Portfolio</h2>
              <p><b>Cash:</b> $${Number(p.cash).toFixed(2)}</p>
              <p><b>Starting Value:</b> $${Number(p.starting_value).toFixed(2)}</p>
              <p><b>Updated:</b> ${escapeHtml(p.updated_at)}</p>
            </div>
            `;
          }

          html += '<h2>Open Positions</h2>' + table(data.open_positions);
          html += '<h2>Recent Transactions</h2>' + table(data.recent_transactions);

          document.getElementById('app').innerHTML = html;
        }

        function table(rows) {
          if (!rows || !rows.length) return '<p>None</p>';
          const cols = Object.keys(rows[0]);
          return `
            <table>
              <thead><tr>${cols.map(c => '<th>' + escapeHtml(c) + '</th>').join('')}</tr></thead>
              <tbody>
                ${rows.map(r => `
                  <tr>${cols.map(c => '<td>' + escapeHtml(r[c]) + '</td>').join('')}</tr>
                `).join('')}
              </tbody>
            </table>
          `;
        }

        load();
        setInterval(load, 30000);
      </script>
    </body>
    </html>
    """
