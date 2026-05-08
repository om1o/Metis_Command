"""
Comms Link — the physical bridge from Metis to the real world.
Handles outbound email (SMTP) and SMS (Twilio, placeholder).
"""

import os
import smtplib
from email.message import EmailMessage


def _email_credentials(user_id: str | None = None) -> tuple[str, str, str, int]:
    """
    Resolve SMTP credentials in priority order:
      1. The user's manager_config (filled via the setup wizard).
      2. EMAIL_USER / EMAIL_PASS / SMTP_HOST / SMTP_PORT env vars.

    Returns (user, password, host, port). Empty strings when nothing is set.
    """
    cfg_user = cfg_pass = ""
    cfg_host = "smtp.gmail.com"
    cfg_port = 465
    try:
        import manager_config as _mc
        cfg = _mc.get_config(user_id or "default")
        cfg_user = (cfg.email_username or "").strip()
        cfg_pass = (cfg.email_password or "").strip()
        cfg_host = (cfg.email_smtp_host or "smtp.gmail.com").strip() or "smtp.gmail.com"
        cfg_port = int(cfg.email_smtp_port or 465)
    except Exception:
        pass
    user = cfg_user or os.getenv("EMAIL_USER", "")
    password = cfg_pass or os.getenv("EMAIL_PASS", "")
    host = cfg_host if cfg_user else os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = cfg_port if cfg_user else int(os.getenv("SMTP_PORT", "465"))
    return user, password, host, port


class CommsLink:
    def send_human_email(
        self, to_email: str, subject: str, body: str,
        *, user_id: str | None = None,
    ) -> bool:
        """
        Send an email via SMTP. Credentials come from the user's
        manager_config first, environment vars second.
        """
        try:
            from comms_policy import is_allowed
            if not is_allowed("email"):
                print("[CommsLink] Email blocked by Director tool settings.")
                return False
        except ImportError:
            pass

        smtp_user, smtp_pass, smtp_host, smtp_port = _email_credentials(user_id)

        if not smtp_user or not smtp_pass:
            print("[CommsLink] Missing EMAIL_USER or EMAIL_PASS in .env.")
            return False

        msg = EmailMessage()
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        try:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
                smtp.login(smtp_user, smtp_pass)
                smtp.send_message(msg)
            print(f"[CommsLink] Email sent to {to_email}.")
            return True
        except Exception as e:
            print(f"[CommsLink] Email send error: {e}")
            return False

    def send_text_message(self, phone_number: str, message: str) -> bool:
        """
        Send an SMS via Twilio.
        Requires TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM in environment.
        """
        try:
            from comms_policy import is_allowed
            if not is_allowed("sms"):
                print("[CommsLink] SMS blocked by Director tool settings.")
                return False
        except ImportError:
            pass

        sid = os.getenv("TWILIO_SID")
        token = os.getenv("TWILIO_TOKEN")
        from_number = os.getenv("TWILIO_FROM")

        if not all([sid, token, from_number]):
            print(f"[CommsLink] (SIMULATED) SMS to {phone_number}: '{message}'")
            return False

        try:
            from twilio.rest import Client
            client = Client(sid, token)
            client.messages.create(body=message, from_=from_number, to=phone_number)
            print(f"[CommsLink] SMS sent to {phone_number}.")
            return True
        except Exception as e:
            print(f"[CommsLink] SMS send error: {e}")
            return False

    def place_outbound_call(self, to_number: str, twiml_url: str | None = None) -> bool:
        """
        Place an outbound voice call via Twilio REST.
        Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM. Optionally set TWILIO_CALL_TWIML_URL
        to a URL that returns TwiML, or pass twiml_url.

        If not configured, logs and returns False.
        """
        try:
            from comms_policy import is_allowed
            if not is_allowed("phone"):
                print("[CommsLink] Outbound call blocked by Director tool settings.")
                return False
        except ImportError:
            pass

        sid = os.getenv("TWILIO_SID")
        token = os.getenv("TWILIO_TOKEN")
        from_number = os.getenv("TWILIO_FROM")
        default_url = os.getenv("TWILIO_CALL_TWIML_URL", "")
        url = twiml_url or default_url

        if not all([sid, token, from_number, url]):
            print(
                "[CommsLink] (SIMULATED) Outbound call — missing Twilio or TWIML URL. "
                f"to={to_number}"
            )
            return False

        try:
            from twilio.rest import Client
            client = Client(sid, token)
            client.calls.create(to=to_number, from_=from_number, url=url)
            print(f"[CommsLink] Outbound call started to {to_number}.")
            return True
        except Exception as e:
            print(f"[CommsLink] Outbound call error: {e}")
            return False
