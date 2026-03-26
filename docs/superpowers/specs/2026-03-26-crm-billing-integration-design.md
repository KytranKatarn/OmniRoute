# CRM Billing Integration — Revenue Dashboard + Subscription Management

**Date**: 2026-03-26
**Project**: #195 — Unified Stripe Billing — Platform-Wide Payment Integration
**Status**: Design Approved
**Scope**: Sub-Projects 5+6 combined — CRM Billing tab (revenue dashboard, subscription management, customer billing table, webhook handlers, Stripe API integration)
**Depends on**: Stripe Core (Sub-Project 1, completed)

---

## Problem Statement

CRM needs to be the central billing hub — showing revenue data, managing subscriptions for all products, and syncing with Stripe via webhooks. Admin manages everything from CRM; customers don't self-serve (admin-managed model).

---

## Deliverable 1: CRM Billing Tab — Revenue Dashboard

**New tab**: "Billing" added to CRM module alongside existing tabs.

### Revenue Cards (Top Row)

| Card | Metric | Source |
|------|--------|--------|
| Total MRR | Sum of active monthly subscription amounts | `billing_products` + Stripe subscriptions |
| Active Subscriptions | Count of active subscriptions | `billing_events` (subscription.created - deleted) |
| Churn Rate | Cancellations last 30d / active at start | `billing_events` |
| Avg LTV | Total revenue / total customers | `billing_events` (invoice.paid) |
| Payment Success | Successful / total payments (last 30d) | `billing_events` |
| Total Revenue | All-time revenue sum | `billing_events` (invoice.paid) |

### Revenue Over Time Chart

- Line chart: monthly revenue, new subscriptions, cancellations
- Interactive: zoom, pan, time range filters (1M/3M/6M/1Y/ALL)
- Same Chart.js pattern as Code Health Lines Over Time
- Data from `billing_events` aggregated by month

### Subscription Distribution Chart

- Donut chart: tier breakdown (Free/Pro/Business/Enterprise)
- Secondary donut: product breakdown (KSM/Store/Invoice)
- Interactive hover with counts and percentages
- Data from `billing_products` + active subscriptions

---

## Deliverable 2: Customer Billing Table

### Table Columns

| Column | Data |
|--------|------|
| Customer | Name + email (from billing_customers or crm_customers) |
| Product | Which module (KSM, Store, etc.) |
| Tier/Plan | Current subscription tier or product name |
| MRR | Monthly amount for this customer |
| Status | active / past_due / cancelled / trialing |
| Last Payment | Date + amount of most recent invoice.paid |
| Actions | View, Edit Tier, Cancel, Portal, Stripe Link |

### Features
- Sortable by any column
- Filterable by status, product, tier
- Search by name/email
- Pagination (25/50/100 per page)
- Export to CSV

---

## Deliverable 3: Admin Subscription Management

### Actions from CRM

| Action | How | Stripe API |
|--------|-----|-----------|
| Create subscription | Select customer + product/price → Stripe Checkout or direct create | `stripe.Subscription.create()` |
| Change tier | Select new price → modify subscription | `stripe.Subscription.modify(items=[{price: new_price_id}])` |
| Cancel subscription | Confirm dialog → cancel | `stripe.Subscription.cancel()` |
| Open Portal | Generate portal URL for customer | `stripe.billing_portal.Session.create()` |
| View in Stripe | Link to Stripe Dashboard customer page | `https://dashboard.stripe.com/customers/{cus_id}` |
| Export CSV | Download all billing data | Local query, no Stripe API |

### Create Subscription Flow
1. Admin selects CRM contact (or creates new billing customer)
2. Selects product module (KSM, Store, etc.)
3. Selects price/tier from `billing_products`
4. System creates Stripe subscription → webhook confirms → table updates
5. If customer has no payment method, generates Checkout Session URL for admin to share

---

## Deliverable 4: Stripe API Integration in CRM

### Local-First Data Strategy

Most billing data comes from local tables (fast, no API calls):
- `billing_customers` — customer ↔ Stripe mapping
- `billing_events` — all webhook events (payments, subscriptions, etc.)
- `billing_products` — registered products/prices

### Live Stripe Queries (on-demand)

For customer detail views and real-time data:
- `stripe.Subscription.list(customer=cus_xxx)` — active subscriptions
- `stripe.Invoice.list(customer=cus_xxx, limit=10)` — recent invoices
- `stripe.Customer.retrieve(cus_xxx)` — balance, default payment method
- `stripe.PaymentIntent.list(customer=cus_xxx, limit=5)` — recent payments

### Revenue Calculation Functions

```python
def calculate_mrr():
    """Sum active subscription amounts from billing_events."""
    # Count active subscriptions from subscription.created - subscription.deleted events

def calculate_churn_rate(days=30):
    """Cancellations in period / active at start of period."""

def calculate_ltv():
    """Total revenue from invoice.paid events / unique customers."""

def calculate_payment_success_rate(days=30):
    """invoice.paid / (invoice.paid + invoice.payment_failed) in period."""

def get_revenue_by_month():
    """Aggregate invoice.paid amounts by month for chart."""

def get_subscription_distribution():
    """Count active subscriptions grouped by product + tier."""
```

---

## Deliverable 5: Webhook Handlers for CRM

### Handlers Registered with Stripe Core Dispatcher

| Event Prefix | Handler | What It Does |
|-------------|---------|-------------|
| `customer.subscription.created` | `_handle_subscription_created` | Log new subscription, link to CRM contact, update metrics |
| `customer.subscription.updated` | `_handle_subscription_updated` | Tier change, status change, update local records |
| `customer.subscription.deleted` | `_handle_subscription_deleted` | Mark cancelled, update churn metrics |
| `invoice.paid` | `_handle_invoice_paid` | Record payment amount+date, update revenue |
| `invoice.payment_failed` | `_handle_payment_failed` | Flag as past_due, create system notification |
| `customer.created` | `_handle_customer_created` | Sync to billing_customers if not exists |
| `customer.updated` | `_handle_customer_updated` | Sync email/name changes |

### Handler Registration

In CRM module init or app startup:

```python
from services.billing_webhook import register_billing_handler

register_billing_handler("customer.subscription.created", _handle_subscription_created)
register_billing_handler("customer.subscription.updated", _handle_subscription_updated)
register_billing_handler("customer.subscription.deleted", _handle_subscription_deleted)
register_billing_handler("invoice.paid", _handle_invoice_paid)
register_billing_handler("invoice.payment_failed", _handle_payment_failed)
register_billing_handler("customer.created", _handle_customer_created)
register_billing_handler("customer.updated", _handle_customer_updated)
```

### System Notifications

Payment failures and cancellations generate `system_notifications`:
- Type: `alert` for payment failures, `warning` for cancellations
- Visibility: `admin`
- Linked to CRM customer for quick access

---

## Deliverable 6: CRM ↔ Billing Customer Linking

### Linking Table

```sql
CREATE TABLE IF NOT EXISTS crm_billing_link (
    id SERIAL PRIMARY KEY,
    crm_customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
    billing_customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
    linked_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(crm_customer_id),
    UNIQUE(billing_customer_id)
);
```

### Auto-Linking
- When a CRM contact subscribes (via admin action), link is created automatically
- When a Stripe customer is created with matching email, auto-link to CRM contact
- CRM billing tab shows both linked contacts (with full CRM data) and unlinked billing-only customers
- Admin can manually link/unlink

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `database/migrations/205_crm_billing.sql` | crm_billing_link table |
| Create | `platform_v2/tools/crm/billing_routes.py` | Billing tab API routes |
| Create | `platform_v2/tools/crm/billing_service.py` | Revenue calculations, Stripe queries, subscription management |
| Create | `platform_v2/tools/crm/billing_handlers.py` | Webhook event handlers |
| Modify | `platform_v2/tools/crm/__init__.py` | Register billing routes + handlers |
| Modify | `platform_v2/templates/tools/crm.html` | Add Billing tab with dashboard, table, charts |
| Modify | `platform_v2/static/js/crm.js` (or inline) | Billing tab JS (charts, table, actions) |

---

## Out of Scope

- Customer self-service billing portal (customers don't manage their own billing)
- Automated dunning (payment retry logic — Stripe handles this)
- Tax calculation (Stripe Tax — future)
- Multi-currency support
- Refund processing (manual via Stripe Dashboard for now)
- Store Builder product catalog integration (Sub-Project 3)
- Invoice creation/sending (Sub-Project 4)

---

## Success Criteria

1. CRM Billing tab shows 6 revenue metric cards with live data
2. Revenue Over Time chart renders with monthly data points
3. Subscription distribution chart shows tier/product breakdown
4. Customer billing table lists all billing customers with status, MRR, last payment
5. Admin can create subscription for a customer from CRM
6. Admin can change tier, cancel subscription, open Stripe Portal from CRM
7. CSV export downloads full billing customer list
8. Webhook handlers update CRM data on subscription/payment events
9. Payment failure generates system notification
10. CRM contacts auto-linked to billing customers by email match
