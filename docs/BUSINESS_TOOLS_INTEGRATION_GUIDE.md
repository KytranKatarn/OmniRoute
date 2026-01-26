# Business Tools Integration Guide

**Created:** January 17, 2026
**Purpose:** Comprehensive guide for A.R.C.H.I.E. Business Tools integration

---

## Overview

This guide covers the complete integration of Business Tools modules for STORE.KytranEmpowerment.com:

- **CRM** - Customer management
- **Invoicing** - Subscription billing
- **Email Manager** - Communications
- **Scheduler** - Calendar & renewals
- **Analytics** - Unified metrics
- **Automations** - N8N workflows
- **Social Media** - Command center
- **Call Center** - TELUS 1-800
- **Store Builder** - E-commerce (existing)
- **Website Studio** - Website deployment (existing)

---

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    BUSINESS TOOLS INTEGRATION HUB                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   WEBSITE    │───▶│    STORE     │───▶│     CRM      │              │
│  │   STUDIO     │    │   BUILDER    │    │  Customers   │              │
│  │              │    │              │    │  Segments    │              │
│  │ STORE.Kytran │    │ Products     │    │  History     │              │
│  │ Empowerment  │    │ Orders       │    │              │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         │                   │                   │                       │
│         │                   ▼                   ▼                       │
│         │           ┌──────────────┐    ┌──────────────┐              │
│         │           │  INVOICING   │◀──▶│   EMAIL      │              │
│         │           │              │    │   MANAGER    │              │
│         │           │ Subscriptions│    │              │              │
│         │           │ Recurring    │    │ Templates    │              │
│         │           │ PDF Export   │    │ SMTP Config  │              │
│         │           └──────────────┘    └──────────────┘              │
│         │                   │                   │                       │
│         ▼                   ▼                   ▼                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  SCHEDULER   │◀──▶│ CALL CENTER  │◀──▶│  ANALYTICS   │              │
│  │              │    │              │    │              │              │
│  │ Calendar     │    │ TELUS 1-800  │    │ All Metrics  │              │
│  │ Subscriptions│    │ AI Agents    │    │ Dashboards   │              │
│  │ Events       │    │ Escalations  │    │ Reports      │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         │                   │                   │                       │
│         └───────────────────┼───────────────────┘                       │
│                             ▼                                           │
│  ┌──────────────┐    ┌──────────────────┐                              │
│  │ SOCIAL MEDIA │    │   AUTOMATIONS    │                              │
│  │              │    │                  │                              │
│  │ FB/IG/TikTok │    │  N8N Visual      │                              │
│  │ LinkedIn/YT  │    │  Workflow Builder│                              │
│  │ Pinterest    │    │  Business Rules  │                              │
│  └──────────────┘    └──────────────────┘                              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Database Migrations

### Migration 022: CRM Tables
```sql
-- Customer profiles with order history
CREATE TABLE crm_customers (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(50),
    company VARCHAR(200),
    address_line1 VARCHAR(255),
    address_line2 VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(100),
    postal_code VARCHAR(20),
    country VARCHAR(100),
    source VARCHAR(50), -- 'store', 'call_center', 'manual', 'import'
    subscription_tier VARCHAR(50),
    subscription_status VARCHAR(50),
    tags TEXT[],
    notes TEXT,
    total_orders INTEGER DEFAULT 0,
    total_spent DECIMAL(10,2) DEFAULT 0,
    last_order_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Customer interactions log
CREATE TABLE crm_interactions (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES crm_customers(id),
    interaction_type VARCHAR(50), -- 'email', 'call', 'note', 'order', 'support'
    subject VARCHAR(255),
    content TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Customer segments for marketing
CREATE TABLE crm_segments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    description TEXT,
    filter_criteria JSONB, -- dynamic filter rules
    customer_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_crm_customers_email ON crm_customers(email);
CREATE INDEX idx_crm_customers_source ON crm_customers(source);
CREATE INDEX idx_crm_interactions_customer ON crm_interactions(customer_id);
```

### Migration 023: Invoicing Tables
```sql
-- Invoice headers
CREATE TABLE invoices (
    id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    customer_id INTEGER REFERENCES crm_customers(id),
    order_id INTEGER, -- optional link to store orders
    subscription_id INTEGER REFERENCES user_subscriptions(id),
    status VARCHAR(50) DEFAULT 'draft', -- draft, sent, paid, overdue, cancelled
    issue_date DATE DEFAULT CURRENT_DATE,
    due_date DATE,
    subtotal DECIMAL(10,2),
    tax_rate DECIMAL(5,2) DEFAULT 0,
    tax_amount DECIMAL(10,2) DEFAULT 0,
    discount_amount DECIMAL(10,2) DEFAULT 0,
    total DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    notes TEXT,
    terms TEXT,
    payment_method VARCHAR(50),
    paid_at TIMESTAMP,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Invoice line items
CREATE TABLE invoice_items (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    description VARCHAR(500) NOT NULL,
    quantity DECIMAL(10,2) DEFAULT 1,
    unit_price DECIMAL(10,2),
    amount DECIMAL(10,2),
    product_id INTEGER -- optional link to store products
);

-- Company invoice settings
CREATE TABLE invoice_settings (
    id SERIAL PRIMARY KEY,
    company_name VARCHAR(200),
    company_address TEXT,
    company_phone VARCHAR(50),
    company_email VARCHAR(255),
    logo_url VARCHAR(500),
    default_terms TEXT,
    default_notes TEXT,
    invoice_prefix VARCHAR(20) DEFAULT 'INV-',
    next_invoice_number INTEGER DEFAULT 1001,
    tax_rate DECIMAL(5,2) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_invoices_customer ON invoices(customer_id);
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_due_date ON invoices(due_date);
```

### Migration 024: Email Tables
```sql
-- Email templates
CREATE TABLE email_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    subject VARCHAR(255),
    body_html TEXT,
    body_text TEXT,
    template_type VARCHAR(50), -- 'invoice', 'order_confirm', 'shipping', 'renewal', 'welcome'
    variables JSONB, -- available template variables
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Email send logs
CREATE TABLE email_logs (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES email_templates(id),
    recipient VARCHAR(255),
    subject VARCHAR(255),
    status VARCHAR(50), -- 'sent', 'failed', 'bounced', 'opened', 'clicked'
    sent_at TIMESTAMP DEFAULT NOW(),
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP,
    error_message TEXT
);

-- SMTP settings
CREATE TABLE email_settings (
    id SERIAL PRIMARY KEY,
    smtp_host VARCHAR(255),
    smtp_port INTEGER DEFAULT 587,
    smtp_user VARCHAR(255),
    smtp_password_encrypted TEXT,
    from_email VARCHAR(255),
    from_name VARCHAR(255),
    reply_to VARCHAR(255),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_email_logs_recipient ON email_logs(recipient);
CREATE INDEX idx_email_logs_status ON email_logs(status);
```

### Migration 025: Scheduler Tables
```sql
-- Calendar events
CREATE TABLE calendar_events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    event_type VARCHAR(50), -- 'subscription_renewal', 'appointment', 'callback', 'reminder', 'custom'
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    all_day BOOLEAN DEFAULT FALSE,
    recurrence_rule VARCHAR(255), -- iCal RRULE format
    customer_id INTEGER REFERENCES crm_customers(id),
    created_by INTEGER REFERENCES users(id),
    status VARCHAR(50) DEFAULT 'scheduled', -- scheduled, completed, cancelled
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Subscription renewal schedule
CREATE TABLE subscription_schedule (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER REFERENCES user_subscriptions(id),
    customer_id INTEGER REFERENCES crm_customers(id),
    next_billing_date DATE NOT NULL,
    billing_cycle VARCHAR(20), -- 'monthly', 'yearly'
    amount DECIMAL(10,2),
    status VARCHAR(50) DEFAULT 'active', -- active, paused, cancelled
    reminder_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Scheduled automated tasks
CREATE TABLE scheduled_tasks (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50), -- 'send_email', 'generate_invoice', 'charge_subscription', 'callback'
    scheduled_for TIMESTAMP NOT NULL,
    target_type VARCHAR(50), -- 'customer', 'invoice', 'subscription'
    target_id INTEGER,
    parameters JSONB,
    status VARCHAR(50) DEFAULT 'pending', -- pending, completed, failed
    executed_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Reminders
CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    description TEXT,
    remind_at TIMESTAMP NOT NULL,
    customer_id INTEGER REFERENCES crm_customers(id),
    created_by INTEGER REFERENCES users(id),
    is_completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_calendar_events_start ON calendar_events(start_time);
CREATE INDEX idx_subscription_schedule_billing ON subscription_schedule(next_billing_date);
CREATE INDEX idx_scheduled_tasks_scheduled ON scheduled_tasks(scheduled_for, status);
```

### Migration 026: Analytics Tables
```sql
-- Analytics snapshots (daily aggregates)
CREATE TABLE analytics_snapshots (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    snapshot_type VARCHAR(50), -- 'daily', 'weekly', 'monthly'
    metrics JSONB, -- all metrics in JSON format
    created_at TIMESTAMP DEFAULT NOW()
);

-- Custom dashboards
CREATE TABLE analytics_dashboards (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    description TEXT,
    created_by INTEGER REFERENCES users(id),
    is_default BOOLEAN DEFAULT FALSE,
    layout JSONB, -- widget positions
    created_at TIMESTAMP DEFAULT NOW()
);

-- Dashboard widgets
CREATE TABLE analytics_widgets (
    id SERIAL PRIMARY KEY,
    dashboard_id INTEGER REFERENCES analytics_dashboards(id) ON DELETE CASCADE,
    widget_type VARCHAR(50), -- 'revenue', 'customers', 'calls', 'subscriptions', 'chart'
    title VARCHAR(100),
    config JSONB, -- widget-specific configuration
    position_x INTEGER,
    position_y INTEGER,
    width INTEGER,
    height INTEGER
);

CREATE INDEX idx_analytics_snapshots_date ON analytics_snapshots(snapshot_date, snapshot_type);
```

### Migration 027: Social Media Tables
```sql
-- Connected social accounts
CREATE TABLE social_accounts (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(50) NOT NULL, -- 'facebook', 'instagram', 'tiktok', 'twitter', 'linkedin', 'youtube', 'pinterest'
    account_name VARCHAR(255),
    account_id VARCHAR(255),
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMP,
    profile_url VARCHAR(500),
    profile_image VARCHAR(500),
    followers_count INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    connected_by INTEGER REFERENCES users(id),
    connected_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scheduled/published posts
CREATE TABLE social_posts (
    id SERIAL PRIMARY KEY,
    content TEXT,
    media_urls TEXT[], -- array of media URLs
    platforms TEXT[], -- which platforms to post to
    scheduled_for TIMESTAMP,
    published_at TIMESTAMP,
    status VARCHAR(50) DEFAULT 'draft', -- draft, scheduled, published, failed
    engagement_data JSONB, -- likes, shares, comments per platform
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Posting queue
CREATE TABLE social_media_queue (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES social_posts(id),
    account_id INTEGER REFERENCES social_accounts(id),
    scheduled_for TIMESTAMP,
    status VARCHAR(50) DEFAULT 'pending', -- pending, published, failed
    platform_post_id VARCHAR(255), -- ID returned by platform
    error_message TEXT,
    published_at TIMESTAMP
);

-- Social analytics
CREATE TABLE social_analytics (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES social_posts(id),
    platform VARCHAR(50),
    impressions INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT NOW()
);

-- Content templates
CREATE TABLE social_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    content TEXT,
    media_urls TEXT[],
    platforms TEXT[],
    category VARCHAR(50),
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_social_accounts_platform ON social_accounts(platform, is_active);
CREATE INDEX idx_social_posts_status ON social_posts(status, scheduled_for);
CREATE INDEX idx_social_media_queue_scheduled ON social_media_queue(scheduled_for, status);
```

---

## API Endpoints

### CRM Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/crm` | GET | Dashboard |
| `/tools/crm/customers` | GET | List customers |
| `/tools/crm/customers` | POST | Create customer |
| `/tools/crm/customers/<id>` | GET | Customer details |
| `/tools/crm/customers/<id>` | PUT | Update customer |
| `/tools/crm/customers/<id>` | DELETE | Delete customer |
| `/tools/crm/customers/<id>/interactions` | GET | Customer interactions |
| `/tools/crm/customers/<id>/interactions` | POST | Add interaction |
| `/tools/crm/segments` | GET | List segments |
| `/tools/crm/segments` | POST | Create segment |
| `/tools/crm/api/stats` | GET | Dashboard stats |
| `/tools/crm/api/import` | POST | Import customers |

### Invoicing Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/invoicing` | GET | Dashboard |
| `/tools/invoicing/invoices` | GET | List invoices |
| `/tools/invoicing/invoices` | POST | Create invoice |
| `/tools/invoicing/invoices/<id>` | GET | Invoice details |
| `/tools/invoicing/invoices/<id>` | PUT | Update invoice |
| `/tools/invoicing/invoices/<id>` | DELETE | Delete invoice |
| `/tools/invoicing/invoices/<id>/send` | POST | Send invoice email |
| `/tools/invoicing/invoices/<id>/mark-paid` | POST | Mark as paid |
| `/tools/invoicing/invoices/<id>/pdf` | GET | Download PDF |
| `/tools/invoicing/settings` | GET | Company settings |
| `/tools/invoicing/settings` | PUT | Update settings |
| `/tools/invoicing/api/stats` | GET | Invoice stats |

### Email Manager
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/email-manager` | GET | Dashboard |
| `/tools/email-manager/templates` | GET | List templates |
| `/tools/email-manager/templates` | POST | Create template |
| `/tools/email-manager/templates/<id>` | PUT | Update template |
| `/tools/email-manager/templates/<id>` | DELETE | Delete template |
| `/tools/email-manager/send` | POST | Send email |
| `/tools/email-manager/logs` | GET | Email logs |
| `/tools/email-manager/settings` | GET | SMTP settings |
| `/tools/email-manager/settings` | PUT | Update SMTP |
| `/tools/email-manager/api/stats` | GET | Email stats |

### Scheduler Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/scheduler` | GET | Dashboard/Calendar |
| `/tools/scheduler/events` | GET | List events |
| `/tools/scheduler/events` | POST | Create event |
| `/tools/scheduler/events/<id>` | PUT | Update event |
| `/tools/scheduler/events/<id>` | DELETE | Delete event |
| `/tools/scheduler/subscriptions` | GET | Subscription schedule |
| `/tools/scheduler/tasks` | GET | Scheduled tasks |
| `/tools/scheduler/reminders` | GET | Reminders |
| `/tools/scheduler/reminders` | POST | Create reminder |
| `/tools/scheduler/api/stats` | GET | Scheduler stats |

### Analytics Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/analytics` | GET | Main dashboard |
| `/tools/analytics/revenue` | GET | Revenue metrics |
| `/tools/analytics/customers` | GET | Customer metrics |
| `/tools/analytics/calls` | GET | Call center metrics |
| `/tools/analytics/emails` | GET | Email metrics |
| `/tools/analytics/subscriptions` | GET | Subscription metrics |
| `/tools/analytics/social` | GET | Social media metrics |
| `/tools/analytics/dashboards` | GET | Custom dashboards |
| `/tools/analytics/dashboards` | POST | Create dashboard |
| `/tools/analytics/export` | GET | Export data |

### Automations Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/automations` | GET | Workflow dashboard |
| `/tools/automations/workflows` | GET | List N8N workflows |
| `/tools/automations/workflows/<id>/stats` | GET | Workflow stats |
| `/tools/automations/templates` | GET | Pre-built templates |
| `/tools/automations/templates/<id>/import` | POST | Import template |
| `/tools/automations/executions` | GET | Recent executions |
| `/tools/automations/api/stats` | GET | Automation stats |

### Social Media Module
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/social-media` | GET | Command center |
| `/tools/social-media/accounts` | GET | Connected accounts |
| `/tools/social-media/accounts/connect/<platform>` | POST | Connect account |
| `/tools/social-media/accounts/<id>/disconnect` | POST | Disconnect |
| `/tools/social-media/posts` | GET | List posts |
| `/tools/social-media/posts` | POST | Create post |
| `/tools/social-media/posts/<id>` | PUT | Update post |
| `/tools/social-media/posts/<id>` | DELETE | Delete post |
| `/tools/social-media/posts/<id>/publish` | POST | Publish now |
| `/tools/social-media/calendar` | GET | Content calendar |
| `/tools/social-media/analytics` | GET | Social analytics |
| `/tools/social-media/templates` | GET | Content templates |
| `/tools/social-media/api/stats` | GET | Social stats |

---

## Automation Workflows (N8N)

### Pre-Built Templates

| Workflow | Trigger | Actions |
|----------|---------|---------|
| New Customer Welcome | CRM customer created | Send welcome email, add to segment |
| Order Confirmation | Store order placed | Create invoice, send confirmation, update CRM |
| Subscription Renewal | Scheduler date reached | Charge Stripe, generate invoice, send receipt |
| Failed Payment | Stripe webhook | Email reminder, update CRM status, schedule retry |
| Call Escalation | Call Center escalation | Create CRM ticket, notify manager, schedule callback |
| Low Satisfaction | Call rating < 3 | Alert manager, create follow-up task |
| Subscription Canceled | User cancels | Send survey, update CRM, trigger win-back sequence |
| Social Post Published | Post goes live | Log to Analytics, update CRM interaction |
| Social Engagement Alert | High engagement | Notify team, create follow-up task |
| Invoice Overdue | Due date passed | Send reminder, update status, escalate |

---

## TELUS Call Center Setup

### Already Configured
- TELUS Business Connect provider in database
- Webhook endpoint: `/webhook/telus/sip-call`
- Cost: $0.0200/min, Quality: 7/10

### Setup Steps
1. Add 1-800 number to `user_phone_numbers` table
2. Configure AI agent settings
3. Set business hours
4. Link to CRM for customer lookup
5. Add number to STORE.KytranEmpowerment.com contact page

### Required Configuration
```sql
-- Add your 1-800 number
INSERT INTO user_phone_numbers (
    user_id, phone_number, provider_id,
    ai_agent_enabled, ai_agent_config, business_hours
) VALUES (
    1, -- admin user
    '+18001234567', -- your number
    (SELECT id FROM providers WHERE type = 'telus'),
    true,
    '{"greeting": "Hello, thank you for calling Kytran Empowerment...", "transfer_on_escalate": true}',
    '{"monday": "9:00-17:00", "tuesday": "9:00-17:00", ...}'
);
```

---

## STORE.KytranEmpowerment.com Setup

### Prerequisites
- Store Builder configured with products
- Website Studio project created
- Stripe/PayPal payment processing
- Printful integration for fulfillment
- Domain DNS configured

### Setup Steps

1. **Create Website Project**
   - Go to Website Studio
   - Create new project: "KytranEmpowerment Store"
   - Use e-commerce template

2. **Configure Store Integration**
   - Link to Store Builder
   - Add product grid components
   - Add cart/checkout pages

3. **Configure Subscriptions**
   - Set up subscription tiers (Free/Pro/Business/Enterprise)
   - Configure pricing
   - Add subscription signup page

4. **Add Contact Info**
   - Display TELUS 1-800 number
   - Add contact form linked to CRM

5. **Deploy**
   - Configure domain: store.kytranempowerment.com
   - Deploy to hosting
   - Verify SSL

---

## Social Media Platform Setup

### Recommended: Unified API Approach
Use a unified API service to handle OAuth and token management:

- **Late** (getlate.dev) - $10-50/month
- **Ayrshare** - REST API with SDKs
- **Post for Me** - Handles OAuth automatically

### Direct Integration (Alternative)
| Platform | API | Documentation |
|----------|-----|---------------|
| Facebook | Graph API | developers.facebook.com |
| Instagram | Graph API | Same as Facebook |
| TikTok | TikTok API | developers.tiktok.com |
| Twitter/X | API v2 | developer.twitter.com |
| LinkedIn | Marketing API | developer.linkedin.com |
| YouTube | Data API v3 | developers.google.com/youtube |
| Pinterest | API | developers.pinterest.com |

---

## Success Criteria

- [ ] CRM tracks all customers from Store, Call Center, manual entry
- [ ] Invoicing handles one-time and recurring subscription billing
- [ ] Email Manager sends automated transactional emails
- [ ] Scheduler tracks subscription renewals and events
- [ ] Analytics shows unified metrics across all modules
- [ ] Automations provides visual workflow management via N8N
- [ ] Social Media manages all platforms from single dashboard
- [ ] Call Center has Telus 1-800 configured and working
- [ ] STORE.KytranEmpowerment.com is live with subscriptions

---

## Sources & References

**CRM & Invoicing:**
- [n8n CRM Workflow Automation](https://n8n.io/supercharge-your-crm/)
- [n8n Invoiced Integration](https://n8n.io/integrations/invoiced/)
- [CRM Integration Best Practices 2026](https://www.bigtime.net/blogs/crm-for-professional-services/)
- [Best CRM with Invoicing](https://assembly.com/blog/crm-with-invoicing)

**Automation:**
- [n8n AI Workflow Automation 2025](https://blog.thinkbot.agency/n8n-automation-workflows-custom-integrations-ai-2025/)
- [n8n GitHub - 400+ integrations](https://github.com/n8n-io/n8n)

**Social Media:**
- [Late - Unified Social Media API](https://getlate.dev)
- [Postiz - Open Source Social Management](https://postiz.com/)
- [Outstand - Best Unified APIs](https://www.outstand.so/blog/best-unified-social-media-apis-for-devs)
- [Post for Me - OAuth handling](https://www.postforme.dev/)

---

**Document Status:** Complete
**Last Updated:** January 17, 2026
