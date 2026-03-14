# Health Modules Upgrade: Fitness + Therapy + DOC — Design Spec

## Overview

Add DB persistence + Google Calendar integration to all 3 health modules. Each gets history tracking, scheduling via Google Calendar, and upgraded AI chat with user context.

## Shared Migration 169 (all 3 modules)

### Fitness tables
- fitness_workout_logs (user_id, workout_type, exercises JSONB, duration_min, calories, notes, logged_at)
- fitness_goals (user_id, goal_type, target, current, unit, deadline, created_at)

### Therapy tables
- therapy_mood_logs (user_id, mood_score 1-10, energy_score 1-10, notes, tags JSONB, logged_at)
- therapy_sessions (user_id, session_type, notes, exercises_done JSONB, duration_min, logged_at)

### DOC tables
- health_symptom_logs (user_id, symptoms JSONB, severity 1-10, notes, logged_at)
- health_medications (user_id, name, dosage, frequency, start_date, end_date, active bool)

## Shared Calendar Integration

All 3 modules can create Google Calendar events via the existing calendar_service:
- Fitness: "Workout: Upper Body" at scheduled time
- Therapy: "Therapy Session" or "Mood Check-in" reminders
- DOC: "Doctor Appointment" or "Take Medication" reminders

Pattern: POST /api/{module}/schedule — body: {title, datetime, duration} → calls calendar_service.create_event if Google account connected, else stores as local reminder.

## Per-Module Route Additions

### Fitness (+6 routes)
- POST /api/workout/log — log completed workout (persist to DB)
- GET /api/workout/history — past workouts
- POST /api/goals — set fitness goal
- GET /api/goals — list goals with progress
- POST /api/schedule — schedule workout in Google Calendar
- GET /api/stats — workout stats (weekly count, total calories, streak)

### Therapy (+6 routes)
- POST /api/mood — log mood (persist to DB now)
- GET /api/mood/history — mood timeline
- POST /api/session — log therapy session
- GET /api/session/history — past sessions
- POST /api/schedule — schedule therapy session in calendar
- GET /api/stats — mood trends, session count, streak

### DOC (+6 routes)
- POST /api/symptoms — log symptoms (persist to DB)
- GET /api/symptoms/history — symptom timeline
- POST /api/medications — add medication
- GET /api/medications — list active medications
- POST /api/schedule — schedule appointment in calendar
- GET /api/stats — health stats, symptom frequency

## AI Chat Upgrade (all 3)

Inject recent user history into Bridge system prompt:
- Fitness: last 5 workouts + current goals
- Therapy: last 5 mood entries + session history
- DOC: recent symptoms + active medications

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | database/migrations/169_health_modules.sql | 6 tables for all 3 modules |
| Create | platform_v2/tools/fitness/services/fitness_service.py | Workout + goal + schedule (~100 lines) |
| Create | platform_v2/tools/therapy/services/therapy_service.py | Mood + session + schedule (~100 lines) |
| Create | platform_v2/tools/doc/services/doc_service.py | Symptom + medication + schedule (~100 lines) |
| Modify | platform_v2/tools/fitness/routes.py | +6 routes + AI context |
| Modify | platform_v2/tools/therapy/routes.py | +6 routes + AI context |
| Modify | platform_v2/tools/doc/routes.py | +6 routes + AI context |

Total: ~300 lines new services, ~120 lines route additions. No frontend changes (existing templates already have UI for these features).
