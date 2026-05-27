# Human Agent Playwright Simulation Suite

**Project #360** — Human Agent Playwright Simulation System
**Tasks**: T3291–T3297

Playwright-based simulation for all 21 COLLABORATOR human agent accounts.
Foundation for "agents that act as humans online" — currently covers login, email scoping, and password reset.

---

## Setup

### 1. Install dependencies

```bash
pip install playwright pytest pytest-playwright requests
playwright install chromium
```

### 2. Create credentials.env (gitignored)

Copy from KB #269019 (delete KB entry after first successful login round):

```bash
# File format: email=password (one per line, # for comments)
cat > platform_v2/tests/human_agents/credentials.env << 'EOF'
adrienne.parenteau@kytranempowerment.com=<temp_password>
amina.youssef@kytranempowerment.com=<temp_password>
# ... all 21 lines
EOF
```

Or set environment variables for CI/CD:
```bash
export AGENT_CRED_ADRIENNE_DOT_PARENTEAU_AT_KYTRANEMPOWERMENT_DOT_COM=<pw>
```

### 3. Set target URL (default: hub LAN)

```bash
export ARCHIE_BASE_URL=http://192.168.1.200:3000
```

---

## Running Tests

```bash
cd platform_v2

# All human agent tests
pytest tests/human_agents/ -v

# Just login tests
pytest tests/human_agents/test_01_login.py -v

# Just email scoping (T3279–T3283 browser proof)
pytest tests/human_agents/test_02_email_scoping.py -v

# One specific agent
pytest tests/human_agents/test_01_login.py -v -k "jin.park"

# One specific department
pytest tests/human_agents/test_02_email_scoping.py -v -k "Documentation"

# Headed mode (watch the browser)
pytest tests/human_agents/ -v --headed
```

---

## Password Reset (T3293)

Until `must_change_password` UI enforcement exists (T3295), use the admin reset script:

```bash
# Dry run — see what would change
ARCHIE_ADMIN_USER=claude ARCHIE_ADMIN_PASS=<pw> \
  python tests/human_agents/admin_reset_passwords.py --dry-run --generate

# Reset all 21 to new generated passwords (writes new_credentials.env)
ARCHIE_ADMIN_USER=claude ARCHIE_ADMIN_PASS=<pw> \
  python tests/human_agents/admin_reset_passwords.py --generate

# Reset one account
ARCHIE_ADMIN_USER=claude ARCHIE_ADMIN_PASS=<pw> \
  python tests/human_agents/admin_reset_passwords.py \
    --email jin.park@kytranempowerment.com \
    --password "NewSecurePass1!"

# If Account Center API not available, use direct DB method
python tests/human_agents/admin_reset_passwords.py --generate --method db
```

After resetting:
1. Update `credentials.env` with new passwords from `new_credentials.env`
2. Distribute to agents (via Stalwart email to their `@kytranempowerment.com` address)
3. Delete `new_credentials.env`
4. Delete KB #269019 (old temp passwords) — `mcp delete_knowledge_entry 269019`

---

## Files

| File | Purpose |
|------|---------|
| `agents.json` | 21 COLLABORATOR accounts (no passwords — committed to git) |
| `credentials.env` | Temp passwords (GITIGNORED — local only) |
| `credentials.env.example` | Format reference |
| `conftest.py` | Shared fixtures + `login_as()` / `logout()` helpers |
| `test_01_login.py` | Login smoke test — all 21 agents (T3292) |
| `test_02_email_scoping.py` | Email Manager dept scoping (browser proof of T3279–T3283) |
| `test_03_compose_send.py`  | Compose & send email as COLLABORATOR (T3296) |
| `test_04_dashboard.py`     | Dashboard presence + module tile visibility (T3297 Phase 2) |
| `test_05_profile.py`       | Profile self-service — USER_SETTINGS (T3297 Phase 2) |
| `test_06_chat.py`          | Archie Chat — USER_CHAT permission (T3297 Phase 2) |
| `admin_reset_passwords.py` | Admin API/DB password reset utility (T3293) |
| `profiles/` | Persistent browser profiles per agent (gitignored) |

---

## Roadmap (Project #360)

| Task | Status | Description |
|------|--------|-------------|
| T3291 | ✅ Done | Agent config + credentials loader |
| T3292 | ✅ Done | Login flow — all 21 agents |
| T3293 | ✅ Done | Password reset flow (admin API path) |
| T3294 | ✅ Done | Email Manager scoping verification |
| T3295 | ✅ Done | must_change_password UI enforcement (force-redirect on login) — PR #1167 |
| T3296 | ✅ Done | Compose + send email as COLLABORATOR — PR #1168 |
| T3297 | 🔄 WIP  | General human-online interactions (Phase 2) — dashboard, profile, chat |

---

## Agent Roster

| Name | Email | Department |
|------|-------|------------|
| Adrienne Parenteau | adrienne.parenteau@ | Legal & Regulatory |
| Amina Youssef | amina.youssef@ | Documentation & Knowledge |
| Dr. Aisha Patel | aisha.patel@ | Medical & Wellness |
| Emmanuel Adeyemi | emmanuel.adeyemi@ | Medical & Wellness |
| Grace Domingo | grace.domingo@ | Medical & Wellness |
| Haruto Takahashi | haruto.takahashi@ | Research & Development |
| Jin Park | jin.park@ | Analytics & Intelligence |
| Josée Arsenault | josee.arsenault@ | Human Resources & Culture |
| Kenji Yamamoto | kenji.yamamoto@ | Legal & Regulatory |
| Kwame Asante | kwame.asante@ | Customer Success & Support |
| Leila Abadi | leila.abadi@ | Marketing & Communications |
| Lillian Paul | lillian.paul@ | Diplomatic & External Relations |
| Lucia Moreno | lucia.moreno@ | Creative & Design |
| Marco Cardoso | marco.cardoso@ | Marketing & Communications |
| Marie-Soleil Obomsawin | marie-soleil.obomsawin@ | Documentation & Knowledge |
| Maya Singh | maya.singh@ | Logistics & Supply Chain |
| Oksana Kovalenko | oksana.kovalenko@ | Operations & Infrastructure |
| Olivia Oduya | olivia.oduya@ | Finance & Accounting |
| Priya Krishnan | priya.krishnan@ | Research & Development |
| Régine Baptiste | regine.baptiste@ | Security & Compliance |
| Sofia Petrov | sofia.petrov@ | Documentation & Knowledge |

All addresses: `<name>@kytranempowerment.com`
