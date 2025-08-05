import warnings
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"pkg_resources is deprecated as an API.*"
)

import os
import json
import logging
import time
import requests
import feedparser
import pytz
import keep_alive  # Flask keep-alive server
keep_alive.keep_alive()  # Lancement du keep-alive (ne pas dupliquer)

from datetime import datetime, time as dt_time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
)

# === CONFIG ===
TOKEN   = os.getenv("TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
TIMEZONE = pytz.timezone("Europe/Paris")

# === LOGGING ===
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === STATE ===
STATE_PATH = Path("state.json")
if STATE_PATH.exists():
    state = json.loads(STATE_PATH.read_text())
else:
    state = {"alerts": [], "portfolio": [], "watchlist": [], "last_prices": {}}
state.setdefault("alerts", [])
state.setdefault("portfolio", [])
state.setdefault("watchlist", [])
state.setdefault("last_prices", {})

def save_state():
    STATE_PATH.write_text(json.dumps(state, indent=2))
save_state()

# === UTILITIES ===
def get_price(symbol: str):
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    key = symbol.upper()
    if key not in mapping:
        return None
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={mapping[key]}&vs_currencies=eur",
            timeout=10
        ).json()
        return resp[mapping[key]]["eur"]
    except Exception as e:
        logger.warning(f"get_price error for {symbol}: {e}")
        return None

def fetch_news_items():
    feeds = [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://cointelegraph.com/rss"
    ]
    items = []
    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:
            title = entry.title
            link = entry.link
            summary = getattr(entry, "summary", "")
            items.append(f"{title}\n{summary}\n{link}")
    return items

HOT_PROJECTS = [
    {"name": "Starknet", "description": "Layer 2 sur Ethereum basé sur STARK, scalable et sécurisé."},
    {"name": "Fuel Network", "description": "Execution layer optimisé pour rollups modulaires."},
    {"name": "Celestia",     "description": "Blockchain modulaire pour la disponibilité des données."},
]

def fallback_analysis(news_items, projects):
    summary = "📝 *Résumé simple des actus* :\n"
    for ni in news_items:
        summary += f"• {ni.splitlines()[0]}\n"
    analysis = "\n🚀 *Analyse projets* :\n"
    for p in projects:
        hype = 7
        desc = p["description"].lower()
        for kw in ("modulaire", "optimisé", "scalable"):
            if kw in desc:
                hype += 1
        hype = min(hype, 10)
        analysis += (
            f"*{p['name']}*\n"
            f"Technologie: 8/10 - moderne.\n"
            f"Opportunité: 8/10 - cas clair.\n"
            f"Hype: {hype}/10 - mots-clés. ({p['description']})\n\n"
        )
    return summary + analysis

# === HANDLERS ===
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bienvenue sur CryptoBotActu ! Tapez /menu pour commencer.")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmds = ["/start", "/menu", "/help", "/news", "/projects", "/analyse", "/airdrops", "/price", "/alerts", "/portfolio", "/watchlist"]
    await update.message.reply_text("Commandes disponibles:\n" + "\n".join(cmds))

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📰 Actus",    callback_data="news")],
        [InlineKeyboardButton("🚀 Projets",  callback_data="projects")],
        [InlineKeyboardButton("🧠 Analyse", callback_data="analyse")],
        [InlineKeyboardButton("🎁 Airdrops",callback_data="airdrops")],
        [InlineKeyboardButton("💰 Prix",     callback_data="price")],
        [InlineKeyboardButton("🔔 Alertes",  callback_data="alerts")],
        [InlineKeyboardButton("📈 Portefeuille", callback_data="portfolio")],
        [InlineKeyboardButton("🔍 Watchlist",    callback_data="watchlist")],
    ]
    await update.message.reply_text("📋 Menu :", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query  # type: ignore
    data = q.data
    await q.answer()
    if data == "news":
        news = fetch_news_items()
        text = "📰 *Actus Crypto :*\n" + "\n".join(f"• {n.splitlines()[0]}" for n in news)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    elif data == "projects":
        text = "🚀 *Projets :*\n" + "\n".join(f"• *{p['name']}* – {p['description']}" for p in HOT_PROJECTS)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    elif data == "analyse":
        await q.edit_message_text(fallback_analysis(fetch_news_items(), HOT_PROJECTS), parse_mode=ParseMode.MARKDOWN)
    elif data == "airdrops":
        await q.edit_message_text("🎁 *Airdrops :* ZKSync, LayerZero, Aleo", parse_mode=ParseMode.MARKDOWN)
    elif data == "price":
        btc, eth, sol = get_price("BTC"), get_price("ETH"), get_price("SOL")
        text = "💰 *Prix :*\n"
        text += f"• BTC : {btc:.2f} €\n" if btc else ''
        text += f"• ETH : {eth:.2f} €\n" if eth else ''
        text += f"• SOL : {sol:.2f} €"    if sol else ''
        await q.edit_message_text(text or "Erreur récupération prix.", parse_mode=ParseMode.MARKDOWN)
    elif data == "alerts":
        if not state["alerts"]:
            await q.edit_message_text("Aucune alerte définie.")
        else:
            lines = [f"ID {a.get('id',i+1)}: {a['symbol']} {a['operator']} {a['price']}€" for i,a in enumerate(state["alerts"])]
            await q.edit_message_text("\n".join(lines))
    elif data == "portfolio":
        if not state["portfolio"]:
            await q.edit_message_text("Portefeuille vide.")
        else:
            total = 0
            lines = []
            for p in state["portfolio"]:
                price = get_price(p["symbol"])
                if price:
                    val = price * p["quantity"]
                    pnl = (price - p["avg_price"]) / p["avg_price"] * 100
                    total += val
                    lines.append(f"{p['symbol']}: {p['quantity']}×{price:.2f}€ = {val:.2f}€ ({pnl:+.2f}%)")
            lines.append(f"\nTotal : {total:.2f}€")
            await q.edit_message_text("\n".join(lines))
    elif data == "watchlist":
        if not state["watchlist"]:
            await q.edit_message_text("Watchlist vide.")
        else:
            out = []
            for s in state["watchlist"]:
                pr = get_price(s)
                out.append(f"{s}: {pr:.2f}€" if pr else f"{s}: indisponible")
            await q.edit_message_text("🔍 Watchlist :\n" + "\n".join(out))

# === BACKGROUND JOBS ===
async def check_alerts(app):
    for a in state["alerts"]:
        cur = get_price(a["symbol"])
        if cur and ((a["operator"] == ">" and cur > a["price"]) or (a["operator"] == "<" and cur < a["price"])):
            await app.bot.send_message(chat_id=CHAT_ID, text=f"🚨 {a['symbol']} vaut {cur:.2f}€ (cond {a['operator']} {a['price']})")

async def build_and_send_report(app):
    now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M")
    news = fetch_news_items()
    btc, eth, sol = get_price("BTC"), get_price("ETH"), get_price("SOL")
    def delta(o,n): return (n-o)/o*100 if o else None
    parts = []
    for sym, price in (("BTC",btc),("ETH",eth),("SOL",sol)):
        if price is not None:
            prev = state["last_prices"].get(sym)
            if prev is not None:
                d = delta(prev, price)
                sign = "+" if d>=0 else ""
                parts.append(f"{sym} {price:.0f}€ ({sign}{d:.1f}%)")
            else:
                parts.append(f"{sym} {price:.0f}€")
    ultra = f"📌 {now} | " + " • ".join(parts)
    sent = await app.bot.send_message(chat_id=CHAT_ID, text=ultra, parse_mode=ParseMode.MARKDOWN)

    top = [n.splitlines()[0] for n in news[:3]]
    summary = [f"📈 *Synthèse – {now}*"] + [f"• {h}" for h in top]
    await app.bot.send_message(chat_id=CHAT_ID, text="\n".join(summary), parse_mode=ParseMode.MARKDOWN)

    details = "📰 *Actus détaillées* :\n" + "\n".join(f"• {n.splitlines()[0]}" for n in news)
    await app.bot.send_message(chat_id=CHAT_ID, text=details, parse_mode=ParseMode.MARKDOWN, reply_to_message_id=sent.message_id)

    # update last_prices
    for sym,val in (("BTC",btc),("ETH",eth),("SOL",sol)):
        if val is not None:
            state["last_prices"][sym] = val
    save_state()

# === MAIN ===
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    # Ajoute d'autres handlers ici si besoin

    # scheduling
    jq: JobQueue = app.job_queue
    jq.run_repeating(lambda ctx: check_alerts(ctx.application), interval=300, first=10)
    for h in (6, 12, 20):
        jq.run_daily(lambda ctx: build_and_send_report(ctx.application),
                     time=dt_time(h,0,tzinfo=TIMEZONE))

    # polling auto-reconnect (SANS reconnect_interval !)
    while True:
        try:
            logger.info("Démarrage du polling Telegram…")
            app.run_polling()
            break
        except Exception as e:
            logger.error("Erreur polling, retrying in 5s: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    main()
