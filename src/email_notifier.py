"""
Email Notifier Module — LeetCode Daily Auto-Solver
Dispatches rich HTML reports containing:
  - Run Status (Accepted, Already Solved, Failed)
  - Problem Details (ID, Title, Difficulty, Link, Tags)
  - Full Accepted Solution Code
  - Algorithmic Explanation & Complexity Analysis via Gemini AI
"""

import os
import smtplib
import logging
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Dispatches beautiful, responsive HTML execution reports via SMTP."""

    def __init__(
        self,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        recipient: Optional[str] = None,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
    ):
        self.user = smtp_user or os.environ.get("SMTP_USER", "")
        self.password = smtp_password or os.environ.get("SMTP_PASSWORD", "")
        self.recipient = recipient or os.environ.get("NOTIFICATION_EMAIL", self.user)
        self.host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.port = int(os.environ.get("SMTP_PORT", smtp_port))

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password and self.recipient)

    def send_report(
        self,
        result: Dict[str, Any],
        code: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> bool:
        """
        Build and send the daily solve summary email.
        Returns True if sent, False if skipped or failed.
        """
        if not self.is_configured:
            logger.info("ℹ️ SMTP credentials not configured (SMTP_USER/SMTP_PASSWORD). Skipping email.")
            return False

        problem = result.get("problem") or {}
        status = result.get("status", "unknown")
        pid = problem.get("id", "?")
        title = problem.get("title", "Daily Challenge")
        difficulty = problem.get("difficulty", "Medium")
        slug = problem.get("slug", "")

        status_emoji = {
            "accepted": "🎉 [ACCEPTED]",
            "already_solved": "✅ [ALREADY SOLVED]",
            "failed": "❌ [FAILED]",
            "error": "⚠️ [ERROR]",
        }.get(status, f"ℹ️ [{status.upper()}]")

        subject = f"{status_emoji} LeetCode #{pid}: {title} ({difficulty})"

        html_body = self._render_html(
            result=result,
            code=code,
            explanation=explanation,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"LeetCode Auto-Solver <{self.user}>"
        msg["To"] = self.recipient

        # Plaintext fallback
        plain_text = f"LeetCode #{pid}: {title}\nStatus: {status}\nDifficulty: {difficulty}\n"
        if slug:
            plain_text += f"Problem URL: https://leetcode.com/problems/{slug}/\n"
        if explanation:
            plain_text += f"\n--- Explanation ---\n{explanation}\n"
        if code:
            plain_text += f"\n--- Solution Code ---\n{code}\n"

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            logger.info(f"Connecting to SMTP server {self.host}:{self.port}...")
            server = smtplib.SMTP(self.host, self.port, timeout=20)
            server.ehlo()
            if self.port in (587, 25):
                server.starttls()
                server.ehlo()
            server.login(self.user, self.password)
            server.sendmail(self.user, [self.recipient], msg.as_string())
            server.quit()
            logger.info(f"✅ Notification email successfully sent to {self.recipient}!")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to dispatch email notification: {e}")
            return False

    def _render_html(
        self,
        result: Dict[str, Any],
        code: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> str:
        problem = result.get("problem") or {}
        pid = problem.get("id", "?")
        title = problem.get("title", "Daily Problem")
        difficulty = problem.get("difficulty", "Medium")
        slug = problem.get("slug", "")
        tags = problem.get("tags") or []
        status = result.get("status", "unknown")
        sub = result.get("submission") or {}
        runtime = sub.get("runtime", "N/A")
        memory = sub.get("memory", "N/A")
        attempts = sub.get("attempts", 1)
        err = result.get("error")

        diff_colors = {
            "Easy": "#00b8a3",
            "Medium": "#ffc01e",
            "Hard": "#ff375f",
        }
        diff_color = diff_colors.get(difficulty, "#ffc01e")

        status_styles = {
            "accepted": ("#22c55e", "rgba(34, 197, 94, 0.15)", "ACCEPTED"),
            "already_solved": ("#38bdf8", "rgba(56, 189, 248, 0.15)", "ALREADY SOLVED"),
            "failed": ("#ef4444", "rgba(239, 68, 68, 0.15)", "SUBMISSION FAILED"),
            "error": ("#f97316", "rgba(249, 115, 22, 0.15)", "PIPELINE ERROR"),
        }
        status_color, status_bg, status_text = status_styles.get(
            status, ("#a1a1aa", "rgba(161, 161, 170, 0.15)", status.upper())
        )

        problem_url = f"https://leetcode.com/problems/{slug}/" if slug else "#"
        pid = html.escape(str(pid))
        title = html.escape(str(title))
        difficulty = html.escape(str(difficulty))
        runtime = html.escape(str(runtime))
        memory = html.escape(str(memory))
        attempts = html.escape(str(attempts))
        err = html.escape(str(err)) if err else None

        tags_html = "".join(
            [f"<span style='display:inline-block;background:#27272a;color:#a1a1aa;padding:3px 8px;border-radius:4px;font-size:11px;margin-right:6px;margin-bottom:6px;'>{html.escape(str(t))}</span>" for t in tags]
        )

        explanation_html = ""
        if explanation:
            # Convert newlines to formatted paragraphs / lists
            formatted_exp = html.escape(explanation).replace("\n\n", "</p><p style='margin:8px 0;line-height:1.6;'>").replace("\n", "<br>")
            explanation_html = f"""
            <div style="background:#18181b;border:1px solid #27272a;border-radius:8px;padding:18px;margin-top:20px;">
              <h3 style="margin:0 0 12px 0;font-size:14px;color:#f4f4f5;text-transform:uppercase;letter-spacing:1px;">💡 Approach & Explanation</h3>
              <div style="color:#d4d4d8;font-size:13px;line-height:1.6;">
                <p style="margin:0 0 8px 0;">{formatted_exp}</p>
              </div>
            </div>
            """

        code_html = ""
        if code:
            escaped_code = html.escape(code.strip())
            code_html = f"""
            <div style="background:#18181b;border:1px solid #27272a;border-radius:8px;padding:18px;margin-top:20px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:10px;">
                <h3 style="margin:0;font-size:14px;color:#f4f4f5;text-transform:uppercase;letter-spacing:1px;">💻 Solution Code (Python3)</h3>
              </div>
              <pre style="background:#09090b;color:#a5f3fc;padding:14px;border-radius:6px;font-family:'SF Mono','Fira Code',Consolas,monospace;font-size:12px;line-height:1.5;overflow-x:auto;margin:0;border:1px solid #27272a;"><code>{escaped_code}</code></pre>
            </div>
            """

        error_html = ""
        if err:
            error_html = f"""
            <div style="background:rgba(239, 68, 68, 0.1);border:1px solid #ef4444;border-radius:8px;padding:14px;margin-top:20px;color:#fca5a5;font-size:13px;">
              <strong>Error Trace:</strong> {err}
            </div>
            """

        stats_section = ""
        if status == "accepted":
            stats_section = f"""
            <div style="display:flex;gap:12px;margin-top:16px;">
              <div style="background:#27272a;padding:10px 14px;border-radius:6px;flex:1;">
                <div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;">Runtime</div>
                <div style="color:#22c55e;font-size:16px;font-weight:700;">{runtime}</div>
              </div>
              <div style="background:#27272a;padding:10px 14px;border-radius:6px;flex:1;">
                <div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;">Memory</div>
                <div style="color:#38bdf8;font-size:16px;font-weight:700;">{memory}</div>
              </div>
              <div style="background:#27272a;padding:10px 14px;border-radius:6px;flex:1;">
                <div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;">Attempts</div>
                <div style="color:#f59e0b;font-size:16px;font-weight:700;">{attempts}</div>
              </div>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin:0;padding:24px;background:#09090b;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#f4f4f5;">
          <div style="max-width:680px;margin:0 auto;background:#121216;border:1px solid #27272a;border-radius:12px;overflow:hidden;box-shadow:0 10px 25px rgba(0,0,0,0.5);">
            <!-- Header -->
            <div style="padding:24px;border-bottom:1px solid #27272a;background:linear-gradient(180deg, #18181b 0%, #121216 100%);">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <span style="font-size:13px;font-weight:700;color:#f59e0b;letter-spacing:1px;text-transform:uppercase;">🧠 LeetCode Daily Pulse</span>
                <span style="background:{status_bg};color:{status_color};border:1px solid {status_color};padding:4px 10px;border-radius:9999px;font-size:11px;font-weight:700;letter-spacing:0.5px;">{status_text}</span>
              </div>
              <h1 style="margin:0 0 8px 0;font-size:20px;font-weight:700;color:#ffffff;">
                <a href="{problem_url}" target="_blank" style="color:#ffffff;text-decoration:none;">[{pid}] {title}</a>
              </h1>
              <div style="display:flex;align-items:center;gap:10px;margin-top:8px;">
                <span style="color:{diff_color};font-size:12px;font-weight:700;background:rgba(255,255,255,0.05);padding:2px 8px;border-radius:4px;">{difficulty}</span>
                <div style="margin-left:4px;">{tags_html}</div>
              </div>
              {stats_section}
            </div>

            <!-- Content Area -->
            <div style="padding:24px;">
              {error_html}
              {explanation_html}
              {code_html}

              <div style="text-align:center;margin-top:28px;padding-top:18px;border-top:1px solid #27272a;color:#71717a;font-size:11px;">
                Sent automatically by your <a href="https://github.com/itsyunus/LeetCode_autoSOL" target="_blank" style="color:#f59e0b;text-decoration:none;">LeetCode Auto-Solver</a> on GitHub Actions.<br>
                Keep the streak alive. The grind never stops.
              </div>
            </div>
          </div>
        </body>
        </html>
        """
