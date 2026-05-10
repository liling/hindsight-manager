"""Email service for sending notifications."""

import logging
from smtplib import SMTPException
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from hindsight_manager.config import Settings

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

logger = logging.getLogger(__name__)


class EmailService(Protocol):
    """Email service protocol."""

    async def send_verification_email(
        self, email: str, code: str, session: AsyncSession | None = None
    ) -> bool:
        """Send verification email with code."""
        ...

    async def send_password_reset_email(
        self, email: str, reset_link: str, session: AsyncSession | None = None
    ) -> bool:
        """Send password reset email with link."""
        ...


class SMTPEmailService:
    """SMTP email service implementation."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.use_tls = use_tls

    async def send_verification_email(
        self, email: str, code: str, session: AsyncSession | None = None
    ) -> bool:
        """Send verification email with code."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "验证您的邮箱地址"
            msg["From"] = self.from_email
            msg["To"] = email

            text = f"您的验证码是: {code}\n\n验证码有效期为10分钟。"
            html = f"""
            <html>
              <body>
                <h2>验证您的邮箱地址</h2>
                <p>您的验证码是:</p>
                <h1 style="color: #0066cc;">{code}</h1>
                <p>验证码有效期为10分钟。</p>
                <p>如果您没有请求此验证码，请忽略此邮件。</p>
              </body>
            </html>
            """

            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Verification email sent to {email}")
            return True
        except SMTPException as e:
            logger.error(f"Failed to send verification email to {email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending verification email to {email}: {e}")
            return False

    async def send_password_reset_email(
        self, email: str, reset_link: str, session: AsyncSession | None = None
    ) -> bool:
        """Send password reset email with link."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "重置您的密码"
            msg["From"] = self.from_email
            msg["To"] = email

            text = f"点击以下链接重置您的密码: {reset_link}\n\n链接有效期为1小时。"
            html = f"""
            <html>
              <body>
                <h2>重置您的密码</h2>
                <p>点击以下按钮重置您的密码:</p>
                <p>
                  <a href="{reset_link}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">重置密码</a>
                </p>
                <p>或复制以下链接到浏览器:</p>
                <p style="word-break: break-all; color: #0066cc;">{reset_link}</p>
                <p>链接有效期为1小时。</p>
                <p>如果您没有请求重置密码，请忽略此邮件。</p>
              </body>
            </html>
            """

            part1 = MIMEText(text, "plain")
            part2 = MIMEText(html, "html")
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Password reset email sent to {email}")
            return True
        except SMTPException as e:
            logger.error(f"Failed to send password reset email to {email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending password reset email to {email}: {e}")
            return False


class SendGridEmailService:
    """SendGrid email service implementation."""

    def __init__(self, api_key: str, from_email: str):
        if not SENDGRID_AVAILABLE:
            raise ImportError("sendgrid package is not installed")
        self.api_key = api_key
        self.from_email = from_email
        self.client = sendgrid.SendGridAPIClient(api_key=api_key)

    async def send_verification_email(
        self, email: str, code: str, session: AsyncSession | None = None
    ) -> bool:
        """Send verification email with code."""
        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=email,
                subject="验证您的邮箱地址",
                html_content=f"""
                <html>
                  <body>
                    <h2>验证您的邮箱地址</h2>
                    <p>您的验证码是:</p>
                    <h1 style="color: #0066cc;">{code}</h1>
                    <p>验证码有效期为10分钟。</p>
                    <p>如果您没有请求此验证码，请忽略此邮件。</p>
                  </body>
                </html>
                """,
            )

            response = self.client.send(message)
            if response.status_code in (200, 202):
                logger.info(f"Verification email sent to {email}")
                return True
            else:
                logger.error(f"SendGrid failed with status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to send verification email to {email}: {e}")
            return False

    async def send_password_reset_email(
        self, email: str, reset_link: str, session: AsyncSession | None = None
    ) -> bool:
        """Send password reset email with link."""
        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=email,
                subject="重置您的密码",
                html_content=f"""
                <html>
                  <body>
                    <h2>重置您的密码</h2>
                    <p>点击以下按钮重置您的密码:</p>
                    <p>
                      <a href="{reset_link}" style="background-color: #0066cc; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">重置密码</a>
                    </p>
                    <p>或复制以下链接到浏览器:</p>
                    <p style="word-break: break-all; color: #0066cc;">{reset_link}</p>
                    <p>链接有效期为1小时。</p>
                    <p>如果您没有请求重置密码，请忽略此邮件。</p>
                  </body>
                </html>
                """,
            )

            response = self.client.send(message)
            if response.status_code in (200, 202):
                logger.info(f"Password reset email sent to {email}")
                return True
            else:
                logger.error(f"SendGrid failed with status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to send password reset email to {email}: {e}")
            return False


def get_email_service(settings: Settings) -> EmailService | None:
    """Get email service based on settings."""
    if settings.email_service == "smtp":
        if not all(
            [
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_username,
                settings.smtp_password,
                settings.smtp_from_email,
            ]
        ):
            logger.error("SMTP email service configured but missing required settings")
            return None
        return SMTPEmailService(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_email=settings.smtp_from_email,
            use_tls=settings.smtp_use_tls,
        )
    elif settings.email_service == "sendgrid":
        if not all([settings.sendgrid_api_key, settings.sendgrid_from_email]):
            logger.error("SendGrid email service configured but missing required settings")
            return None
        return SendGridEmailService(
            api_key=settings.sendgrid_api_key,
            from_email=settings.sendgrid_from_email,
        )
    else:
        logger.warning(f"Unknown email service: {settings.email_service}")
        return None
