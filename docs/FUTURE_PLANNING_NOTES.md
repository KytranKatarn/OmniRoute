# A.R.C.H.I.E. Future Planning Notes

**Purpose:** Capture architectural ideas for future phases (not for immediate implementation)

---

## Business Tools Directory Module (Future)

**Date Noted:** 2026-01-17

### Current State
- `/directory` redirects to `/business/directory`
- `business/directory.html` - Professional team directory (Inter font)
- `templates/directory.html` - Matrix-style green directory (duplicate?)
- Website Studio has `/api/directory` endpoints

### Proposed Architecture

**Team Management vs Directory:**
| Component | Purpose | Location |
|-----------|---------|----------|
| Team Management | Internal admin for AI/human staff | Admin Operations |
| Directory Module | Public-facing team page for websites | Business Tools |
| Website Designer | Shows Directory as integrated "project" | Website Designer > Projects |

**Service Tier Model:**
| Tier | Name | Description |
|------|------|-------------|
| Tier 1 | Self-Service | User manages domain, SSL, connections, business tools |
| Tier 2 | Managed Service | KytranEmpowerment manages everything for client |

**Subdomain Pattern for Business Tools:**
```
directory.{client-domain}.com  - Team/Staff Directory
store.{client-domain}.com      - E-commerce (from Store Builder)
support.{client-domain}.com    - Call Center
crm.{client-domain}.com        - Customer Relations
billing.{client-domain}.com    - Invoicing
```

**Website Designer Integration:**
- Projects Tab shows linked modules (Store, Directory, custom pages)
- Domain routing configured in Website Designer
- Each Business Tool is a resellable module

### Implementation Priority
- **Phase 1 (Current):** Admin Ops, Dev Tools, Admin Tools navigation
- **Phase 2 (Next):** Business Tools, Standalone Apps, Creation Tools
- **Phase 3 (Future):** Directory Module migration, Service Tier system

---

## Notes
- Clean up duplicate directory files when implementing
- Consider Account Center for human user management (Business Tools use case)
- Pool Management pattern could apply to other managed services

---

*This document captures ideas for future planning sessions. Not for immediate implementation.*
