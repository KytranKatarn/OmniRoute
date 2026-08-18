"""Domain registry for the P.R.O.B.E. translation audit system."""

from __future__ import annotations

EXTERNAL_DOMAINS: list[dict] = [
    {
        "name": "kytranempowerment_com",
        "translations_url": "https://kytranempowerment.com/data/translations.json",
        "pages": [
            "https://kytranempowerment.com/",
            "https://kytranempowerment.com/about.html",
            "https://kytranempowerment.com/ai-directors.html",
            "https://kytranempowerment.com/services.html",
            "https://kytranempowerment.com/gov-watch.html",
            "https://kytranempowerment.com/civic-watch.html",
            "https://kytranempowerment.com/legal-watch.html",
            "https://kytranempowerment.com/market-watch.html",
            "https://kytranempowerment.com/contact.html",
            "https://kytranempowerment.com/membership.html",
        ],
        "active_languages": ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"],
        "deploy_method": "hostinger",
        "active": True,
    },
    {
        "name": "creed_ai_org",
        "translations_url": "https://creed-ai.org/data/translations.json",
        "pages": [
            "https://creed-ai.org/",
            "https://creed-ai.org/about.html",
            "https://creed-ai.org/governance.html",
            "https://creed-ai.org/manifesto.html",
            "https://creed-ai.org/programs.html",
            "https://creed-ai.org/papers/wp-001-transparency-standards.html",
            "https://creed-ai.org/papers/wp-002-agent-welfare.html",
            "https://creed-ai.org/papers/wp-003-compliance-gap.html",
        ],
        "active_languages": ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"],
        "deploy_method": "hostinger",
        "active": True,
    },
    {
        "name": "kytran_gov_watch",
        "translations_url": "https://gov.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://gov.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
    {
        "name": "kytran_civic_watch",
        "translations_url": "https://civic.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://civic.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
    {
        "name": "kytran_legal_watch",
        "translations_url": "https://legal.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://legal.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
    {
        "name": "kytran_market_watch",
        "translations_url": "https://market.kytranempowerment.com/data/translations.json",
        "pages": [
            "https://market.kytranempowerment.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
    {
        "name": "what_the_fact_com",
        "translations_url": "https://what-the-fact.com/static/data/translations.json",  # /data/ 404s — the app serves /static/data/ (#5750)
        "pages": [
            "https://what-the-fact.com/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
    {
        "name": "what_the_fact_tech",
        "translations_url": "https://what-the-fact.tech/data/translations.json",
        "pages": [
            "https://what-the-fact.tech/",
        ],
        "active_languages": ["en", "fr", "es", "ai"],
        "deploy_method": "vps",
        "active": True,
    },
]
