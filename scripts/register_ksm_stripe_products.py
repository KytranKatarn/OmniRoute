#!/usr/bin/env python3
"""One-time script: create KSM Stripe products+prices and register in billing_products.

Run inside Docker:
    docker exec archie_platform python3 /mnt/archie_brain/scripts/register_ksm_stripe_products.py
"""

import sys

sys.path.insert(0, "/app")

import stripe
import stripe.error
from services.stripe_service import init_stripe, is_stripe_configured, register_product

# ── KSM product definitions ──────────────────────────────────────────────────

PRODUCTS = [
    {"name": "KSM Pro", "amount_cents": 2900, "tier": "pro"},
    {"name": "KSM Business", "amount_cents": 4900, "tier": "business"},
    {"name": "KSM Enterprise", "amount_cents": 9900, "tier": "enterprise"},
]


def main() -> None:
    init_stripe()

    if not is_stripe_configured():
        print("ERROR: Stripe is not configured (missing or placeholder keys). Exiting.")
        sys.exit(1)

    for prod in PRODUCTS:
        tier = prod["tier"]
        name = prod["name"]
        amount = prod["amount_cents"]

        print(f"\n--- Creating {name} (${amount / 100:.0f}/month, tier={tier}) ---")

        # 1. Create Stripe Product
        try:
            stripe_product = stripe.Product.create(
                name=name,
                metadata={"module": "ksm", "tier": tier},
            )
            print(f"  Stripe Product: {stripe_product.id}")
        except stripe.error.StripeError as e:
            print(f"  ERROR creating Stripe product: {e}")
            sys.exit(1)

        # 2. Create Stripe Price
        try:
            stripe_price = stripe.Price.create(
                product=stripe_product.id,
                unit_amount=amount,
                currency="usd",
                recurring={"interval": "month"},
                metadata={"tier": tier},
            )
            print(f"  Stripe Price:   {stripe_price.id}")
        except stripe.error.StripeError as e:
            print(f"  ERROR creating Stripe price: {e}")
            sys.exit(1)

        # 3. Register locally in billing_products
        row = register_product(
            module="ksm",
            stripe_product_id=stripe_product.id,
            stripe_price_id=stripe_price.id,
            name=name,
            amount_cents=amount,
            currency="usd",
            interval="month",
            description=f"{name} subscription — ${amount / 100:.0f}/month",
            active=True,
        )
        print(f"  Registered locally: billing_products row id={row.get('id', '?')}")

    print("\nAll 3 KSM products created and registered successfully.")


if __name__ == "__main__":
    main()
