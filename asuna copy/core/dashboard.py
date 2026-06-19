"""Dashboard web en lecture seule (aiohttp).

Sert quelques pages HTML montrant les statistiques du/des serveur(s) : messages
par jour (graphique), classements (messages, économie, niveaux) et usage des
commandes. Aucune donnée sensible (token, etc.) n'est exposée.
"""

from __future__ import annotations

import html
import json

from aiohttp import web

from core import stats

# ── Gabarit & style ───────────────────────────────────────────────────────────
_CSS = """
:root { --bg:#0f1014; --card:#1a1c23; --accent:#b57edc; --text:#e8e8ee; --muted:#9aa0ab; }
* { box-sizing:border-box; }
body { margin:0; font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header { padding:24px 32px; border-bottom:1px solid #262830; display:flex; align-items:center; gap:16px; }
header img { width:48px; height:48px; border-radius:50%; }
h1 { font-size:22px; margin:0; }
.wrap { max-width:1000px; margin:0 auto; padding:24px 32px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:24px; }
.card { background:var(--card); border:1px solid #262830; border-radius:14px; padding:18px; }
.card .big { font-size:28px; font-weight:700; color:var(--accent); }
.card .lbl { color:var(--muted); font-size:13px; margin-top:4px; }
.panel { background:var(--card); border:1px solid #262830; border-radius:14px; padding:20px; margin-bottom:24px; }
.panel h2 { font-size:16px; margin:0 0 14px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
td { padding:7px 4px; border-bottom:1px solid #23252d; }
td.r { text-align:right; color:var(--accent); font-variant-numeric:tabular-nums; }
.rank { color:var(--muted); width:32px; }
.muted { color:var(--muted); }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:24px; }
@media (max-width:700px){ .grid2 { grid-template-columns:1fr; } }
footer { color:var(--muted); text-align:center; padding:24px; font-size:13px; }
"""


def _page(title: str, body: str, head_extra: str = "") -> web.Response:
    doc = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style>{head_extra}</head>
<body>{body}<footer>Asuna • Dashboard (lecture seule)</footer></body></html>"""
    return web.Response(text=doc, content_type="text/html")


def _table(rows_html: str) -> str:
    return f"<table>{rows_html}</table>" if rows_html else "<p class='muted'>Aucune donnée pour l'instant.</p>"


def _name(guild, user_id: int) -> str:
    member = guild.get_member(user_id) if guild else None
    return html.escape(member.display_name if member else f"Utilisateur {user_id}")


# ── Handlers ──────────────────────────────────────────────────────────────────
async def _overview(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    guilds = sorted(bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
    total_members = sum(g.member_count or 0 for g in guilds)
    cards = (
        f"<div class='card'><div class='big'>{len(guilds)}</div><div class='lbl'>Serveurs</div></div>"
        f"<div class='card'><div class='big'>{total_members}</div><div class='lbl'>Membres cumulés</div></div>"
        f"<div class='card'><div class='big'>{len(bot.commands) + len(list(bot.tree.walk_commands()))}</div><div class='lbl'>Commandes</div></div>"
    )
    rows = "".join(
        f"<tr><td><a href='/guild/{g.id}'>{html.escape(g.name)}</a></td>"
        f"<td class='r'>{g.member_count or 0}</td></tr>" for g in guilds)
    body = f"""<header><h1>🤖 Asuna — Dashboard</h1></header><div class="wrap">
<div class="cards">{cards}</div>
<div class="panel"><h2>Serveurs</h2>{_table(rows)}</div></div>"""
    return _page("Asuna — Dashboard", body)


async def _guild_page(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    try:
        gid = int(request.match_info["gid"])
    except ValueError:
        raise web.HTTPNotFound()
    guild = bot.get_guild(gid)
    if guild is None:
        return _page("Introuvable", "<div class='wrap'><p>Serveur inconnu ou bot absent.</p>"
                     "<p><a href='/'>← Retour</a></p></div>")
    db = bot.db

    series = await stats.daily_series(db, gid, 14)
    today = await stats.messages_today(db, gid)
    week = await stats.messages_window(db, gid, 7)
    total = await stats.messages_total(db, gid)

    cards = (
        f"<div class='card'><div class='big'>{guild.member_count or 0}</div><div class='lbl'>Membres</div></div>"
        f"<div class='card'><div class='big'>{today}</div><div class='lbl'>Messages aujourd'hui</div></div>"
        f"<div class='card'><div class='big'>{week}</div><div class='lbl'>Messages (7 j)</div></div>"
        f"<div class='card'><div class='big'>{total}</div><div class='lbl'>Messages suivis</div></div>"
    )

    labels = json.dumps([d[5:] for d, _ in series])  # MM-DD
    data = json.dumps([c for _, c in series])

    async def leaderboard(rows, value_key, fmt=lambda v: str(v)):
        out = ""
        for i, r in enumerate(rows):
            out += (f"<tr><td class='rank'>#{i + 1}</td><td>{_name(guild, r['user_id'])}</td>"
                    f"<td class='r'>{fmt(r[value_key])}</td></tr>")
        return out

    chatters = await leaderboard(await stats.top_users(db, gid), "count")
    eco = await leaderboard(await stats.economy_top(db, gid), "total")
    lvls = await leaderboard(await stats.levels_top(db, gid), "xp")
    cmd_rows = await stats.top_commands(db, gid)
    cmds = "".join(f"<tr><td>/{html.escape(r['command'])}</td><td class='r'>{r['count']}</td></tr>" for r in cmd_rows)

    icon = f"<img src='{guild.icon.url}'>" if guild.icon else ""
    chart_js = (
        "<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>"
        "<script>window.addEventListener('load',function(){new Chart("
        "document.getElementById('c'),{type:'line',data:{labels:" + labels +
        ",datasets:[{label:'Messages/jour',data:" + data +
        ",borderColor:'#b57edc',backgroundColor:'rgba(181,126,220,.2)',fill:true,tension:.3}]},"
        "options:{plugins:{legend:{labels:{color:'#e8e8ee'}}},scales:{x:{ticks:{color:'#9aa0ab'}},"
        "y:{ticks:{color:'#9aa0ab'},beginAtZero:true}}}});});</script>")

    body = f"""<header>{icon}<h1>{html.escape(guild.name)}</h1></header><div class="wrap">
<p><a href="/">← Tous les serveurs</a></p>
<div class="cards">{cards}</div>
<div class="panel"><h2>Activité (14 jours)</h2><canvas id="c" height="90"></canvas></div>
<div class="grid2">
  <div class="panel"><h2>🗣️ Top bavards</h2>{_table(chatters)}</div>
  <div class="panel"><h2>💰 Top fortunes</h2>{_table(eco)}</div>
  <div class="panel"><h2>📈 Top niveaux</h2>{_table(lvls)}</div>
  <div class="panel"><h2>⚙️ Commandes utilisées</h2>{_table(cmds)}</div>
</div></div>"""
    return _page(f"{guild.name} — Asuna", body, head_extra=chart_js)


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def build_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.add_routes([
        web.get("/", _overview),
        web.get("/health", _health),
        web.get("/guild/{gid}", _guild_page),
    ])
    return app


async def start_dashboard(bot, host: str, port: int) -> web.AppRunner:
    """Démarre le serveur web et renvoie le runner (à nettoyer à l'arrêt)."""
    runner = web.AppRunner(build_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner
