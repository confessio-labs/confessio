import os
from enum import Enum

import httpx


class TelegramTopic(Enum):
    """Values are the message_thread_id of each topic in the Confessio forum supergroup."""
    NEW_REPORTS = 22
    NEW_IMAGES = 25
    INFRA_ALERTS = 26
    CRAWLING_ALERTS = 28
    CONTACT_FORM = 29
    PB_OCLOCHER = 30
    NEW_SCHEDULES = 31


MAX_TELEGRAM_TEXT = 4096


def send_telegram_alert(message: str, topic: TelegramTopic):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Impossible d'envoyer l'alerte Telegram : la variable d'environnement "
              "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID n'est pas définie.")
        return

    data = {
        "chat_id": chat_id,
        "message_thread_id": topic.value,
        # No parse_mode: alerts embed user-provided text, which would break markdown parsing.
        "text": message[:MAX_TELEGRAM_TEXT],
    }
    response = httpx.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=data)

    if response.status_code != 200:
        print(f"Erreur lors de l'envoi de l'alerte Telegram : "
              f"{response.status_code} - {response.text}")
    else:
        print("Alerte Telegram envoyée avec succès.")


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv()
    send_telegram_alert("Test d'alerte Telegram depuis Confessio.",
                        TelegramTopic.CRAWLING_ALERTS)
