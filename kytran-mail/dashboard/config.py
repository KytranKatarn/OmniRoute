"""Configuration from environment variables."""

import os


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me")
    MAIL_DOMAIN = os.environ.get("MAIL_DOMAIN", "kytranempowerment.com")
    MAIL_HOSTNAME = os.environ.get("MAIL_HOSTNAME", "mail.kytranempowerment.com")
    MAIL_ADMIN_PASSWORD = os.environ.get("MAIL_ADMIN_PASSWORD", "")
    STALWART_ADMIN_URL = os.environ.get("STALWART_API_URL", "https://localhost:443")
