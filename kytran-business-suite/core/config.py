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
        self.KBS_BRIDGE_MODEL = os.getenv("KBS_BRIDGE_MODEL", "qwen2.5-coder:7b")
        self.KBS_WEBHOOK_TIMEOUT = int(os.getenv("KBS_WEBHOOK_TIMEOUT", "10"))

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

        # Stripe subscription price IDs (Stripe Dashboard -> Products -> Prices)
        self.KBS_STRIPE_PRICE_BUSINESS = os.getenv("KBS_STRIPE_PRICE_BUSINESS", "")
        self.KBS_STRIPE_PRICE_ENTERPRISE = os.getenv("KBS_STRIPE_PRICE_ENTERPRISE", "")
        # Add-on / a-la-carte price IDs stored as JSON: {"salon": "price_xxx", ...}
        self.KBS_STRIPE_ADDON_PRICES = os.getenv("KBS_STRIPE_ADDON_PRICES", "{}")

        # Hostinger DNS (subdomain provisioning)
        self.KBS_HOSTINGER_API_KEY = os.getenv("KBS_HOSTINGER_API_KEY", "")
        self.KBS_BASE_DOMAIN = os.getenv("KBS_BASE_DOMAIN", "kytranempowerment.com")
        self.KBS_SUBDOMAIN_TARGET = os.getenv(
            "KBS_SUBDOMAIN_TARGET", "192.168.1.200"
        )

        # Printful
        self.KBS_PRINTFUL_API_KEY = os.getenv("KBS_PRINTFUL_API_KEY", "")

        # RingCentral
        self.KBS_RINGCENTRAL_SERVER_URL = os.getenv(
            "KBS_RINGCENTRAL_SERVER_URL", "https://platform.ringcentral.com"
        )
        self.KBS_RINGCENTRAL_CLIENT_ID = os.getenv("KBS_RINGCENTRAL_CLIENT_ID", "")
        self.KBS_RINGCENTRAL_CLIENT_SECRET = os.getenv("KBS_RINGCENTRAL_CLIENT_SECRET", "")
        self.KBS_RINGCENTRAL_JWT_TOKEN = os.getenv("KBS_RINGCENTRAL_JWT_TOKEN", "")
        self.KBS_RINGCENTRAL_ACCOUNT_ID = os.getenv("KBS_RINGCENTRAL_ACCOUNT_ID", "~")
        self.KBS_RINGCENTRAL_WEBHOOK_SECRET = os.getenv("KBS_RINGCENTRAL_WEBHOOK_SECRET", "")

        # Twilio (SMS fallback)
        self.KBS_TWILIO_ACCOUNT_SID = os.getenv("KBS_TWILIO_ACCOUNT_SID", "")
        self.KBS_TWILIO_AUTH_TOKEN = os.getenv("KBS_TWILIO_AUTH_TOKEN", "")
        self.KBS_TWILIO_PHONE_NUMBER = os.getenv("KBS_TWILIO_PHONE_NUMBER", "")

        # Hostinger Reach (email marketing)
        self.KBS_REACH_API_URL = os.getenv(
            "KBS_REACH_API_URL", "https://api.hostinger.com/reach/v1"
        )
        self.KBS_REACH_API_KEY = os.getenv("KBS_REACH_API_KEY", "")

        # SMS provider preference
        self.KBS_SMS_PROVIDER = os.getenv("KBS_SMS_PROVIDER", "ringcentral")
