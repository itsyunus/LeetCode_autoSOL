"""Optional mobile alerts for LeetCode automation failures."""
import os
import requests


def send_alert(message: str) -> bool:
    sent = False
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    webapp_url = os.environ.get(
        "MINI_APP_URL",
        "https://itsyunus.github.io/LeetCode_autoSOL/login.html"
    )

    if bot_token and chat_id:
        import html
        escaped_msg = html.escape(message)
        text_payload = (
            f"🚨 <b>LeetCode Session Alert</b>\n\n"
            f"• <b>Status:</b> Session Expired\n"
            f"• <b>Details:</b> <code>{escaped_msg}</code>\n\n"
            f"Tap the button below to sign in and automatically renew your session."
        )

        telegram_payload = {
            "chat_id": chat_id,
            "text": text_payload,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "🔐 Log In & Renew Session",
                            "web_app": {"url": webapp_url}
                        }
                    ]
                ]
            }
        }

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=telegram_payload,
                timeout=15,
            )
            response.raise_for_status()
            sent = True
        except requests.RequestException:
            # Fallback to plain text if webapp payload is rejected
            try:
                fallback_resp = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"🚨 LeetCode Session Expired:\n{message}\n\nRenew here: {webapp_url}"},
                    timeout=15,
                )
                fallback_resp.raise_for_status()
                sent = True
            except requests.RequestException:
                pass

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
