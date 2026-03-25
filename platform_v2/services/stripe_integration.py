"""
Stripe Integration Module for A.R.C.H.I.E. Platform
Handles subscriptions, payments, invoices, and webhooks
"""

import os
from database import _get_db_password
import stripe
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ============================================================================
# CUSTOMER MANAGEMENT
# ============================================================================


def get_or_create_stripe_customer(user_id, email, name):
    """Get existing Stripe customer or create new one"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check if customer exists in our database
        cur.execute(
            "SELECT stripe_customer_id FROM stripe_customers WHERE user_id = %s",
            (user_id,),
        )
        result = cur.fetchone()

        if result:
            customer_id = result["stripe_customer_id"]
            cur.close()
            conn.close()
            return customer_id

        # Create new Stripe customer
        customer = stripe.Customer.create(email=email, name=name, metadata={"user_id": user_id})

        # Store in database
        cur.execute(
            """
            INSERT INTO stripe_customers (user_id, stripe_customer_id, email)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET stripe_customer_id = EXCLUDED.stripe_customer_id
        """,
            (user_id, customer.id, email),
        )
        conn.commit()
        cur.close()
        conn.close()

        return customer.id

    except Exception as e:
        print(f"Error creating Stripe customer: {e}")
        raise


# ============================================================================
# SUBSCRIPTION MANAGEMENT
# ============================================================================


def create_subscription(user_id, plan_id, billing_cycle="monthly", trial_days=None):
    """Create a new subscription for user"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user info
        cur.execute("SELECT email, username FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()

        # Get plan info
        cur.execute("SELECT * FROM subscription_plans WHERE id = %s", (plan_id,))
        plan = cur.fetchone()

        if not user or not plan:
            raise ValueError("User or plan not found")

        # Get or create Stripe customer
        customer_id = get_or_create_stripe_customer(user_id, user["email"], user["username"])

        # Get correct price ID
        price_id = plan["stripe_price_id_monthly"] if billing_cycle == "monthly" else plan["stripe_price_id_yearly"]

        if not price_id:
            raise ValueError(f"No Stripe price ID configured for {billing_cycle} billing")

        # Create subscription in Stripe
        subscription_params = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "metadata": {"user_id": user_id, "plan_id": plan_id},
        }

        if trial_days:
            subscription_params["trial_period_days"] = trial_days

        stripe_subscription = stripe.Subscription.create(**subscription_params)

        # Store in database
        cur.execute(
            """
            INSERT INTO subscriptions
            (user_id, plan_id, stripe_subscription_id, stripe_customer_id, status,
             billing_cycle, current_period_start, current_period_end, trial_start, trial_end)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                plan_id,
                stripe_subscription.id,
                customer_id,
                stripe_subscription.status,
                billing_cycle,
                datetime.fromtimestamp(stripe_subscription.current_period_start),
                datetime.fromtimestamp(stripe_subscription.current_period_end),
                (datetime.fromtimestamp(stripe_subscription.trial_start) if stripe_subscription.trial_start else None),
                (datetime.fromtimestamp(stripe_subscription.trial_end) if stripe_subscription.trial_end else None),
            ),
        )

        subscription_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()

        return subscription_id, stripe_subscription

    except Exception as e:
        print(f"Error creating subscription: {e}")
        raise


def cancel_subscription(subscription_id, immediate=False):
    """Cancel a subscription"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get subscription
        cur.execute(
            "SELECT stripe_subscription_id FROM subscriptions WHERE id = %s",
            (subscription_id,),
        )
        result = cur.fetchone()

        if not result:
            raise ValueError("Subscription not found")

        # Cancel in Stripe
        if immediate:
            stripe.Subscription.delete(result["stripe_subscription_id"])
        else:
            stripe.Subscription.modify(result["stripe_subscription_id"], cancel_at_period_end=True)

        # Update database
        cur.execute(
            """
            UPDATE subscriptions
            SET cancel_at_period_end = %s, canceled_at = %s, updated_at = NOW()
            WHERE id = %s
        """,
            (not immediate, datetime.now() if immediate else None, subscription_id),
        )

        conn.commit()
        cur.close()
        conn.close()

        return True

    except Exception as e:
        print(f"Error canceling subscription: {e}")
        raise


def reactivate_subscription(subscription_id):
    """Reactivate a canceled subscription"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT stripe_subscription_id FROM subscriptions WHERE id = %s",
            (subscription_id,),
        )
        result = cur.fetchone()

        if not result:
            raise ValueError("Subscription not found")

        # Reactivate in Stripe
        stripe.Subscription.modify(result["stripe_subscription_id"], cancel_at_period_end=False)

        # Update database
        cur.execute(
            """
            UPDATE subscriptions
            SET cancel_at_period_end = FALSE, canceled_at = NULL, updated_at = NOW()
            WHERE id = %s
        """,
            (subscription_id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return True

    except Exception as e:
        print(f"Error reactivating subscription: {e}")
        raise


# ============================================================================
# WEBHOOK HANDLERS
# ============================================================================


def handle_webhook(payload, signature):
    """Handle Stripe webhook events"""
    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)

        # Log webhook
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO webhook_logs (source, event_type, event_id, payload)
            VALUES ('stripe', %s, %s, %s)
        """,
            (event["type"], event["id"], payload),
        )
        conn.commit()

        # Handle different event types
        if event["type"] == "customer.subscription.created":
            handle_subscription_created(event["data"]["object"])
        elif event["type"] == "customer.subscription.updated":
            handle_subscription_updated(event["data"]["object"])
        elif event["type"] == "customer.subscription.deleted":
            handle_subscription_deleted(event["data"]["object"])
        elif event["type"] == "invoice.paid":
            handle_invoice_paid(event["data"]["object"])
        elif event["type"] == "invoice.payment_failed":
            handle_invoice_payment_failed(event["data"]["object"])
        elif event["type"] == "payment_intent.succeeded":
            handle_payment_succeeded(event["data"]["object"])

        # Mark webhook as processed
        cur.execute(
            """
            UPDATE webhook_logs
            SET processed = TRUE, processed_at = NOW()
            WHERE event_id = %s
        """,
            (event["id"],),
        )
        conn.commit()

        cur.close()
        conn.close()

        return True

    except Exception as e:
        print(f"Webhook error: {e}")
        # Log error
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE webhook_logs
                SET error_message = %s
                WHERE event_id = %s
            """,
                (str(e), event.get("id")),
            )
            conn.commit()
            cur.close()
            conn.close()
        except:
            pass
        raise


def handle_subscription_created(subscription):
    """Handle subscription.created webhook"""
    # Already handled in create_subscription function
    pass


def handle_subscription_updated(subscription):
    """Handle subscription.updated webhook"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE subscriptions
        SET status = %s,
            current_period_start = %s,
            current_period_end = %s,
            cancel_at_period_end = %s,
            updated_at = NOW()
        WHERE stripe_subscription_id = %s
    """,
        (
            subscription["status"],
            datetime.fromtimestamp(subscription["current_period_start"]),
            datetime.fromtimestamp(subscription["current_period_end"]),
            subscription.get("cancel_at_period_end", False),
            subscription["id"],
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


def handle_subscription_deleted(subscription):
    """Handle subscription.deleted webhook"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE subscriptions
        SET status = 'canceled',
            canceled_at = NOW(),
            updated_at = NOW()
        WHERE stripe_subscription_id = %s
    """,
        (subscription["id"],),
    )

    conn.commit()
    cur.close()
    conn.close()


def handle_invoice_paid(invoice):
    """Handle invoice.paid webhook"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get user_id from subscription
    if invoice.get("subscription"):
        cur.execute(
            """
            SELECT user_id FROM subscriptions
            WHERE stripe_subscription_id = %s
        """,
            (invoice["subscription"],),
        )
        result = cur.fetchone()
        user_id = result["user_id"] if result else None
    else:
        user_id = None

    # Store invoice
    cur.execute(
        """
        INSERT INTO invoices
        (user_id, stripe_invoice_id, invoice_number, amount_total, amount_paid,
         amount_due, currency, status, invoice_pdf_url, hosted_invoice_url, paid_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (stripe_invoice_id) DO UPDATE
        SET status = EXCLUDED.status, paid_at = EXCLUDED.paid_at
    """,
        (
            user_id,
            invoice["id"],
            invoice.get("number"),
            invoice["amount_paid"] / 100,
            invoice["amount_paid"] / 100,
            invoice["amount_due"] / 100,
            invoice["currency"],
            "paid",
            invoice.get("invoice_pdf"),
            invoice.get("hosted_invoice_url"),
            (
                datetime.fromtimestamp(invoice["status_transitions"]["paid_at"])
                if invoice["status_transitions"].get("paid_at")
                else None
            ),
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


def handle_invoice_payment_failed(invoice):
    """Handle invoice.payment_failed webhook"""
    conn = get_db()
    cur = conn.cursor()

    # Create notification
    cur.execute(
        """
        INSERT INTO system_notifications (type, title, message, source, visibility)
        VALUES ('error', 'Payment Failed', %s, 'stripe_webhook', 'all')
    """,
        (f"Payment failed for invoice {invoice.get('number', invoice['id'])}",),
    )

    conn.commit()
    cur.close()
    conn.close()


def handle_payment_succeeded(payment_intent):
    """Handle payment_intent.succeeded webhook"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Get user_id from customer
    if payment_intent.get("customer"):
        cur.execute(
            """
            SELECT user_id FROM stripe_customers
            WHERE stripe_customer_id = %s
        """,
            (payment_intent["customer"],),
        )
        result = cur.fetchone()
        user_id = result["user_id"] if result else None
    else:
        user_id = None

    # Store payment
    cur.execute(
        """
        INSERT INTO payments
        (user_id, stripe_payment_intent_id, amount, currency, status, payment_method)
        VALUES (%s, %s, %s, %s, 'succeeded', %s)
    """,
        (
            user_id,
            payment_intent["id"],
            payment_intent["amount"] / 100,
            payment_intent["currency"],
            payment_intent.get("payment_method"),
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def get_subscription_status(user_id):
    """Get user's current subscription status"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT s.*, sp.name as plan_name, sp.limits
        FROM subscriptions s
        JOIN subscription_plans sp ON s.plan_id = sp.id
        WHERE s.user_id = %s
        AND s.status IN ('active', 'trialing')
        ORDER BY s.created_at DESC
        LIMIT 1
    """,
        (user_id,),
    )

    result = cur.fetchone()
    cur.close()
    conn.close()

    return result


def check_subscription_limit(user_id, resource_type):
    """Check if user has reached their subscription limit"""
    subscription = get_subscription_status(user_id)

    if not subscription:
        # Free tier limits
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT limits FROM subscription_plans WHERE slug = 'free'")
        result = cur.fetchone()
        cur.close()
        conn.close()
        limits = result["limits"] if result else {}
    else:
        limits = subscription["limits"]

    # Get current usage
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) as usage
        FROM usage_tracking
        WHERE user_id = %s
        AND resource_type = %s
        AND period_start >= DATE_TRUNC('month', CURRENT_DATE)
    """,
        (user_id, resource_type),
    )

    result = cur.fetchone()
    cur.close()
    conn.close()

    current_usage = result["usage"] if result else 0
    limit = limits.get(resource_type, 0)

    return {
        "limit": limit,
        "usage": current_usage,
        "remaining": max(0, limit - current_usage),
        "exceeded": current_usage >= limit,
    }


def track_usage(user_id, resource_type, amount=1, metadata=None):
    """Track resource usage"""
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO usage_tracking
        (user_id, resource_type, amount, metadata, period_start, period_end)
        VALUES (%s, %s, %s, %s,
                DATE_TRUNC('month', CURRENT_DATE),
                DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day')
    """,
        (user_id, resource_type, amount, metadata),
    )

    conn.commit()
    cur.close()
    conn.close()
