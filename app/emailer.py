"""Email delivery via Resend."""

from __future__ import annotations

import logging
import resend
from .config import settings

logger = logging.getLogger("agenttrafficcop.emailer")

# Initialize Resend with the API key from the environment
resend.api_key = settings.resend_api_key

def send_password_reset_email(to_email: str, reset_token: str) -> bool:
    """Send a password reset link to the user."""
    if not resend.api_key:
        logger.warning("resend_api_key_missing")
        return False

    reset_url = f"https://agenttrafficcop.com/reset.html?token={reset_token}"
    
    html_content = f"""
    <div style="font-family: sans-serif; background: #000; color: #ededed; padding: 40px;">
        <h2 style="color: #10b981;">Reset your AgentTrafficCop password</h2>
        <p>Click the link below to set a new password. This link expires in 1 hour.</p>
        <a href="{reset_url}" style="display: inline-block; background: #ededed; color: #000; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 20px;">Reset Password</a>
        <p style="margin-top: 40px; font-size: 12px; color: #666;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": "AgentTrafficCop <support@agenttrafficcop.com>",
            "to": to_email,
            "subject": "Reset your password",
            "html": html_content
        })
        logger.info("password_reset_email_sent email=%s", to_email)
        return True
    except Exception as e:
        logger.error("email_send_failed error=%s", e)
        return False