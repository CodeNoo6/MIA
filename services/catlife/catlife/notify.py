"""Invitation emails over SMTP, configured with the same EMAIL_* variables LibreChat uses."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

SERVICES = {"gmail": ("smtp.gmail.com", 587), "outlook": ("smtp-mail.outlook.com", 587),
            "hotmail": ("smtp-mail.outlook.com", 587), "yahoo": ("smtp.mail.yahoo.com", 587)}


@dataclass(frozen=True)
class Mailer:
    host: str
    port: int
    username: str
    password: str
    sender: str
    sender_name: str
    encryption: str

    @classmethod
    def from_env(cls) -> Mailer | None:
        """None when SMTP is not configured; invitations then rely on the in-MIA notice alone."""
        service = SERVICES.get(os.environ.get("EMAIL_SERVICE", "").lower(), ("", 0))
        host = os.environ.get("EMAIL_HOST") or service[0]
        sender = os.environ.get("EMAIL_FROM", "")
        if not host or not sender:
            return None
        return cls(host=host, port=int(os.environ.get("EMAIL_PORT") or service[1] or 587),
                   username=os.environ.get("EMAIL_USERNAME", ""), password=os.environ.get("EMAIL_PASSWORD", ""),
                   sender=sender, sender_name=os.environ.get("EMAIL_FROM_NAME") or "MIA",
                   encryption=os.environ.get("EMAIL_ENCRYPTION", "starttls").lower())

    def send(self, message: EmailMessage) -> None:
        message["From"] = f"{self.sender_name} <{self.sender}>"
        smtp_class = smtplib.SMTP_SSL if self.encryption == "tls" or self.port == 465 else smtplib.SMTP
        with smtp_class(self.host, self.port, timeout=20) as smtp:
            if smtp_class is smtplib.SMTP and self.encryption != "none":
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


def invitation(to: str, inviter: str, pets: list[str], code: str, mia_url: str) -> EmailMessage:
    names = ", ".join(pets) if pets else "sus mascotas"
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = f"{inviter} te invitó a cuidar a {names} en MIA"
    text = (f"{inviter} quiere compartir contigo a {names} en MIA (Cuidado animal).\n\n"
            f"Entra a {mia_url} con tu cuenta, abre el agente Cat Life o Dog Life y acepta la invitación "
            f"(código {code}). Verás sus vacunas, recordatorios y citas, y te enterarás de cada cambio.\n")
    message.set_content(text)
    message.add_alternative(
        f"<p><strong>{escape(inviter)}</strong> quiere compartir contigo a <strong>{escape(names)}</strong> "
        f"en MIA (Cuidado animal).</p><p><a href=\"{escape(mia_url)}\">Entra a MIA</a> con tu cuenta, abre el "
        f"agente <strong>Cat Life</strong> o <strong>Dog Life</strong> y acepta la invitación "
        f"(código <code>{code}</code>).</p>"
        "<p>Verás sus vacunas, recordatorios y citas, y te enterarás de cada cambio.</p>", subtype="html")
    return message
