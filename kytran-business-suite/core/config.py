import os


class Config:
    """Environment-based configuration for Kytran Business Suite."""

    def __init__(self):
        # Database
        self.KBS_DB_HOST = os.getenv("KBS_DB_HOST", "kbs-postgres")
        self.KBS_DB_PORT = int(os.getenv("KBS_DB_PORT", "5432"))
        self.KBS_DB_NAME = os.getenv("KBS_DB_NAME", "kbs")
        self.KBS_DB_USER = os.getenv("KBS_DB_USER", "kbs")
        self.KBS_DB_PASSWORD = os.getenv("KBS_DB_PASSWORD", "")

        # Redis
        self.KBS_REDIS_URL = os.getenv("KBS_REDIS_URL", "redis://kbs-redis:6379/0")

        # App
        self.KBS_SECRET_KEY = os.getenv("KBS_SECRET_KEY", "dev-only-change-me")
        self.KBS_DOMAIN = os.getenv("KBS_DOMAIN", "localhost")
        self.KBS_DEFAULT_TIER = os.getenv("KBS_DEFAULT_TIER", "free")
        self.KBS_PORT = int(os.getenv("KBS_PORT", "8090"))
        self.KBS_DEBUG = os.getenv("KBS_DEBUG", "false").lower() == "true"

        # AI Bridge
        self.KBS_BRIDGE_URL = os.getenv("KBS_BRIDGE_URL", "")
        self.KBS_BRIDGE_API_KEY = os.getenv("KBS_BRIDGE_API_KEY", "")

        # Mail
        self.KBS_MAIL_PROVIDER = os.getenv("KBS_MAIL_PROVIDER", "smtp")
        self.KBS_SMTP_HOST = os.getenv("KBS_SMTP_HOST", "")
        self.KBS_SMTP_PORT = int(os.getenv("KBS_SMTP_PORT", "587"))
        self.KBS_SMTP_USER = os.getenv("KBS_SMTP_USER", "")
        self.KBS_SMTP_PASSWORD = os.getenv("KBS_SMTP_PASSWORD", "")
        self.KBS_MAIL_FROM = os.getenv(
            "KBS_MAIL_FROM", "noreply@kytranempowerment.com"
        )

        # Google OAuth
        self.KBS_GOOGLE_CLIENT_ID = os.getenv("KBS_GOOGLE_CLIENT_ID", "")
        self.KBS_GOOGLE_CLIENT_SECRET = os.getenv("KBS_GOOGLE_CLIENT_SECRET", "")

        # Stripe
        self.KBS_STRIPE_SECRET_KEY = os.getenv("KBS_STRIPE_SECRET_KEY", "")
        self.KBS_STRIPE_WEBHOOK_SECRET = os.getenv("KBS_STRIPE_WEBHOOK_SECRET", "")
        self.KBS_STRIPE_PUBLISHABLE_KEY = os.getenv("KBS_STRIPE_PUBLISHABLE_KEY", "")

        # Printful
        self.KBS_PRINTFUL_API_KEY = os.getenv("KBS_PRINTFUL_API_KEY", "")
