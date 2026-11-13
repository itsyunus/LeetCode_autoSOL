"""Optional mobile alerts for LeetCode automation failures."""
import os
import requests


def send_alert(message: str) -> bool:
    sent = False
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if bot_token and chat_id:
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        sent = True

    discord_url = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if discord_url:
        response = requests.post(
            discord_url,
            json={"content": message},
            timeout=15,
        )
        response.raise_for_status()
        sent = True
    return sent


if __name__ == "__main__":
    text = os.environ.get(
        "ALERT_MESSAGE",
        "LeetCode automation needs attention. Open the latest GitHub Actions run.",
    )
    try:
        print("Mobile alert sent." if send_alert(text) else "No mobile alert provider configured.")
    except requests.RequestException as exc:
        print(f"Mobile alert delivery failed: {type(exc).__name__}.")
