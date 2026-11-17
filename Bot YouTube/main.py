import os
import json
import logging
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)

# ================= CONFIGURAZIONE =================
load_dotenv(Path(__file__).with_name(".env"))


def required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Configurazione mancante: {name}. Inseriscila nel file .env.")
    return value


TELEGRAM_TOKEN = required_setting("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(required_setting("ADMIN_CHAT_ID"))
TARGET_CHANNEL_ID = required_setting("TARGET_CHANNEL_ID")
YOUTUBE_API_KEY = required_setting("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = required_setting("YOUTUBE_CHANNEL_ID")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
STATE_FILE = "bot_state.json"
# ==================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


def load_state():
    """Carica l'ultimo stato salvato (iscritti e ultimo video) da file JSON."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_sub_count": None, "last_video_id": None}


def save_state(state):
    """Salva lo stato aggiornato su file JSON."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_youtube_stats():
    """Recupera numero di iscritti e ID dell'ultimo video caricato."""
    # 1. Ottieni numero iscritti e playlist degli upload
    url_channel = (
        f"https://www.googleapis.com/youtube/v3/channels"
        f"?part=statistics,contentDetails&id={YOUTUBE_CHANNEL_ID}&key={YOUTUBE_API_KEY}"
    )
    res_channel = requests.get(url_channel).json()

    if "items" not in res_channel or not res_channel["items"]:
        return None, None, None

    item = res_channel["items"][0]
    sub_count = int(item["statistics"]["subscriberCount"])
    uploads_playlist_id = item["contentDetails"]["relatedPlaylists"]["uploads"]

    # 2. Ottieni l'ultimo video dalla playlist degli upload
    url_playlist = (
        f"https://www.googleapis.com/youtube/v3/playlistItems"
        f"?part=snippet&playlistId={uploads_playlist_id}&maxResults=1&key={YOUTUBE_API_KEY}"
    )
    res_playlist = requests.get(url_playlist).json()

    latest_video_id = None
    latest_video_title = None
    if "items" in res_playlist and res_playlist["items"]:
        snippet = res_playlist["items"][0]["snippet"]
        latest_video_id = snippet["resourceId"]["videoId"]
        latest_video_title = snippet["title"]

    return sub_count, latest_video_id, latest_video_title


# --- TASK PERIODICO IN BACKGROUND ---
async def periodic_youtube_check(context: ContextTypes.DEFAULT_TYPE):
    """Controlla periodicamente YouTube per nuovi iscritti e nuovi video."""
    state = load_state()
    sub_count, latest_video_id, latest_video_title = get_youtube_stats()

    if sub_count is None:
        logging.warning("Impossibile recuperare i dati da YouTube.")
        return

    # 1. Controllo Iscritti YouTube
    last_subs = state.get("last_sub_count")
    if last_subs is not None and sub_count != last_subs:
        diff = sub_count - last_subs
        segno = "📈 +" if diff > 0 else "📉 "
        msg = (
            f"🔔 **Aggiornamento Iscritti YouTube!**\n"
            f"Variazione: {segno}{diff}\n"
            f"Totale attuale: **{sub_count}** iscritti"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="Markdown"
        )
    state["last_sub_count"] = sub_count

    # 2. Controllo Nuovi Video YouTube
    last_vid = state.get("last_video_id")
    if latest_video_id and latest_video_id != last_vid:
        # Evita di spammare al primissimo avvio se last_vid è None
        if last_vid is not None:
            video_url = f"https://www.youtube.com/watch?v={latest_video_id}"
            msg_video = (
                f"🎬 **NUOVO VIDEO APPENA USCITO!**\n\n"
                f"📌 **{latest_video_title}**\n"
                f"👉 Guardalo ora: {video_url}"
            )
            await context.bot.send_message(
                chat_id=TARGET_CHANNEL_ID, text=msg_video, parse_mode="Markdown"
            )
        state["last_video_id"] = latest_video_id

    save_state(state)


# --- MONITORAGGIO NUOVI MEMBRI SU TELEGRAM ---
async def track_telegram_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avvisa l'admin quando qualcuno entra nel gruppo/canale Telegram."""
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    user = result.new_chat_member.user

    # Se l'utente prima non era membro e ora lo è
    if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
        nome = user.full_name
        username = f"(@{user.username})" if user.username else ""
        chat_title = update.effective_chat.title

        msg = (
            f"👤 **Nuovo iscritto su Telegram!**\n"
            f"Chat: {chat_title}\n"
            f"Utente: {nome} {username}\n"
            f"ID: `{user.id}`"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="Markdown"
        )


# --- COMANDI MANUALI ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bot di monitoraggio attivo!\nUsa /stats per vedere i dati in tempo reale."
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mostra subito gli iscritti YouTube e Telegram."""
    sub_count, _, latest_title = get_youtube_stats()
    try:
        tg_members = await context.bot.get_chat_member_count(chat_id=TARGET_CHANNEL_ID)
    except Exception:
        tg_members = "N/D (assicurati che il bot sia admin del canale)"

    msg = (
        f"📊 **STATISTICHE IN TEMPO REALE**\n\n"
        f"🔴 **Iscritti YouTube:** {sub_count if sub_count is not None else 'Errore'}\n"
        f"🔵 **Membri Telegram:** {tg_members}\n"
        f"🎬 **Ultimo video:** {latest_title or 'Nessuno'}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Comandi
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Ascolto nuovi iscritti Telegram
    app.add_handler(ChatMemberHandler(track_telegram_members, ChatMemberHandler.CHAT_MEMBER))

    # Avvio controllo periodico YouTube
    job_queue = app.job_queue
    job_queue.run_repeating(periodic_youtube_check, interval=CHECK_INTERVAL_SECONDS, first=5)

    print("Bot avviato e in ascolto...")
    # allowed_updates include chat_member per tracciare chi entra su Telegram
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

