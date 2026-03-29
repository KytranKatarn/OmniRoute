-- 302: Clean billing_subscriptions table for unified Stripe billing
-- Replaces legacy 'subscriptions' table with architecture aligned to
-- billing_customers / billing_products / billing_events

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id                    SERIAL PRIMARY KEY,
    user_id               INTEGER NOT NULL REFERENCES users(id),
    billing_customer_id   INTEGER NOT NULL REFERENCES billing_customers(id),
    stripe_subscription_id VARCHAR(64) NOT NULL UNIQUE,
    stripe_price_id       VARCHAR(64) NOT NULL,
    module                VARCHAR(64) NOT NULL,
    status                VARCHAR(32) NOT NULL DEFAULT 'incomplete'
        CHECK (status IN ('active', 'trialing', 'past_due', 'canceled',
                          'incomplete', 'incomplete_expired', 'unpaid', 'paused')),
    billing_cycle         VARCHAR(16) DEFAULT 'month'
        CHECK (billing_cycle IN ('month', 'year')),
    current_period_start  TIMESTAMP,
    current_period_end    TIMESTAMP,
    cancel_at_period_end  BOOLEAN DEFAULT FALSE,
    canceled_at           TIMESTAMP,
    trial_start           TIMESTAMP,
    trial_end             TIMESTAMP,
    created_at            TIMESTAMP DEFAULT NOW(),
    updated_at            TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_subs_user ON billing_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_customer ON billing_subscriptions(billing_customer_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_stripe ON billing_subscriptions(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_billing_subs_module ON billing_subscriptions(module);
CREATE INDEX IF NOT EXISTS idx_billing_subs_status ON billing_subscriptions(status);
