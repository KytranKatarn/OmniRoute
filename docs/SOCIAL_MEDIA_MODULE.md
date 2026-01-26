# A.R.C.H.I.E. Social Media Module

**Last Updated:** January 18, 2026
**Location:** `/tools/social_media`
**Category:** Business Tools
**Status:** Live (v2.0)

---

## Overview

The **Social Media Module** is A.R.C.H.I.E.'s comprehensive social media management system. It enables scheduling, publishing, and analytics tracking for Instagram and TikTok (with Facebook and Twitter planned).

### Key Features

- **OAuth 2.0 Integration** - Secure connection to Instagram and TikTok
- **Scheduled Posting** - Queue posts for future publishing
- **Background Worker** - APScheduler processes queue every 60 seconds
- **Encrypted Token Storage** - Fernet encryption for OAuth tokens
- **Cross-Platform Analytics** - Unified metrics dashboard
- **Rate Limit Tracking** - Respects platform API limits

---

## Module Structure

```
platform_v2/tools/social_media/
├── __init__.py              # Blueprint registration
├── routes.py                # API endpoints (~2200 lines)
├── oauth_handler.py         # OAuth 2.0 flows (~660 lines)
├── platform_clients.py      # Instagram/TikTok API clients (~730 lines)
├── analytics_aggregator.py  # Cross-platform analytics (~436 lines)
├── social_worker.py         # Background job processor (~606 lines)
└── encryption.py            # Token encryption (~161 lines)
```

---

## Database Tables

### Core Tables (Existing)

| Table | Purpose |
|-------|---------|
| `social_accounts` | Connected platform accounts |
| `social_posts` | Post content and metadata |
| `social_post_results` | Per-platform performance metrics |
| `social_media_queue` | Scheduled job queue |
| `social_templates` | Reusable content templates |
| `social_campaigns` | Campaign grouping |
| `social_calendar_events` | Calendar visualization |
| `social_media_library` | Media assets |
| `social_analytics` | Historical analytics |

### New Tables (v2.0)

| Table | Purpose |
|-------|---------|
| `social_oauth_tokens` | Encrypted OAuth token storage |
| `social_job_logs` | Job execution history |
| `social_api_rate_limits` | API rate limit tracking |
| `social_platform_config` | Platform OAuth configuration |

---

## API Endpoints

### OAuth Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/oauth/status` | GET | Get OAuth config status for all platforms |
| `/api/oauth/instagram/authorize` | GET | Get Instagram auth URL |
| `/api/oauth/instagram/callback` | GET | Handle Instagram OAuth callback |
| `/api/oauth/tiktok/authorize` | GET | Get TikTok auth URL |
| `/api/oauth/tiktok/callback` | GET | Handle TikTok OAuth callback |
| `/api/oauth/refresh/<id>` | POST | Refresh token for account |
| `/api/oauth/revoke/<id>` | DELETE | Disconnect account |
| `/api/oauth/tokens/expiring` | GET | Get tokens expiring soon |

### Posting Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/posts` | GET | List posts with filters |
| `/api/posts` | POST | Create new post |
| `/api/posts/<id>` | GET | Get post details |
| `/api/posts/<id>` | PUT | Update post |
| `/api/posts/<id>` | DELETE | Delete post |
| `/api/posts/<id>/publish` | POST | Publish immediately |
| `/api/posts/<id>/schedule` | POST | Schedule for future |
| `/api/posts/<id>/status` | GET | Get publish status |

### Queue Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/queue/status` | GET | Queue stats summary |
| `/api/queue/failed` | GET | List failed jobs |
| `/api/queue/<id>/retry` | POST | Retry failed job |
| `/api/queue/<id>/cancel` | DELETE | Cancel pending job |

### Analytics Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analytics` | GET | Basic analytics overview |
| `/api/analytics/overview` | GET | Enhanced analytics (aggregator) |
| `/api/analytics/top-posts` | GET | Top performing posts |
| `/api/analytics/accounts` | GET | Per-account statistics |
| `/api/analytics/frequency` | GET | Posting frequency analysis |
| `/api/analytics/compare` | GET | Period comparison |
| `/api/analytics/refresh` | POST | Trigger immediate refresh |

---

## Platform Integration

### Instagram (via Facebook Graph API)

**API Version:** v18.0
**Scopes:** `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`

**Content Types Supported:**
- Single image posts
- Video posts
- Reels

**Rate Limits:**
- 200 API calls per user per hour
- 25 posts per account per day

### TikTok (Content API)

**API Version:** v2
**Scopes:** `user.info.basic`, `video.publish`, `video.list`

**Content Types Supported:**
- Videos only (3-60 seconds)

**Rate Limits:**
- 100 requests per minute
- 1000 requests per day

---

## Background Worker

The social media worker runs three scheduled jobs:

| Job | Interval | Purpose |
|-----|----------|---------|
| `process_queue` | 60 seconds | Process pending posts |
| `refresh_tokens` | 1 hour | Refresh expiring tokens |
| `fetch_analytics` | 1 hour | Update post metrics |

### Retry Strategy

Failed posts are retried with exponential backoff:
- Retry 1: 1 minute delay
- Retry 2: 5 minute delay
- Retry 3: 15 minute delay
- After 3 failures: Marked as permanently failed

---

## Environment Variables

```env
# Instagram (Facebook) App
INSTAGRAM_APP_ID=your_app_id
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_REDIRECT_URI=https://your-domain.com/tools/social-media/api/oauth/instagram/callback

# TikTok App
TIKTOK_CLIENT_KEY=your_client_key
TIKTOK_CLIENT_SECRET=your_client_secret
TIKTOK_REDIRECT_URI=https://your-domain.com/tools/social-media/api/oauth/tiktok/callback

# Encryption (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
SOCIAL_MEDIA_ENCRYPTION_KEY=your_fernet_key
```

---

## Usage Examples

### Connect Instagram Account

```javascript
// 1. Get authorization URL
fetch('/tools/social-media/api/oauth/instagram/authorize')
  .then(r => r.json())
  .then(data => {
    // Redirect user to Instagram
    window.location.href = data.auth_url;
  });

// 2. Handle callback (automatic)
// User is redirected back with connected account
```

### Schedule a Post

```javascript
// Create post
const post = await fetch('/tools/social-media/api/posts', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    content: 'Check out our new product! #launch',
    media_urls: ['https://example.com/image.jpg'],
    target_platforms: ['instagram']
  })
}).then(r => r.json());

// Schedule for tomorrow 10am
await fetch(`/tools/social-media/api/posts/${post.post.id}/schedule`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    scheduled_at: '2026-01-19T10:00:00'
  })
});
```

### Get Analytics

```javascript
fetch('/tools/social-media/api/analytics/overview?period=30d')
  .then(r => r.json())
  .then(data => {
    console.log('Total views:', data.analytics.totals.views);
    console.log('Engagement rate:', data.analytics.totals.engagement_rate);
  });
```

---

## Security

- **Token Encryption**: All OAuth tokens encrypted with Fernet
- **CSRF Protection**: State tokens for OAuth flows
- **Rate Limiting**: Respects platform API limits
- **Access Control**: Requires login, user can only access own data

---

## Related Documentation

- `MASTER_STATUS_AND_ROADMAP_2026.md` - Platform roadmap
- `UI_STYLE_GUIDE.md` - UI styling standards
- `DATABASE_SCHEMA_DOCUMENTATION.md` - Full schema reference

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial UI and mock endpoints |
| 2.0 | Jan 18, 2026 | Full OAuth, posting, analytics |

---

*Social Media Module - Manage your social presence from A.R.C.H.I.E.*
