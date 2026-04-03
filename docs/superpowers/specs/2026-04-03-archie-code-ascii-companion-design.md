# A.R.C.H.I.E. Code CLI — ASCII Companion Widget

**Project**: #217 — A.R.C.H.I.E. Code CLI Platform Integration
**Phase**: 3 (Polish)
**Date**: 2026-04-03
**Status**: Approved

---

## Problem

The ARCHIE Code TUI has no visual presence for ARCHIE herself. The user interacts with a text chat but there's no character, no personality indicator, no visual feedback on what the engine is doing. Velxar (Claude plugin companion rabbit) showed that a small ASCII character adds life to a CLI.

## Solution: Compact ASCII Companion Widget

A pixel-art female face rendered in the bottom-right corner of the TUI chat panel. She has 7 expressions that change based on engine state, idle animations (blink, hair sway), and a personality-flavored status line showing real system state.

### Character Design — Straight Flow Face

```
    ╭───╮
   ╱▓▓▓▓▓╲
  │▓╭───╮▓│
  │▓│◕ ◕│▓│
  ╰─│ ◡ │─╯
   ▓╰───╯▓
   ▓▓   ▓▓
  A.R.C.H.I.E.
   ✦ ready
```

- 9 lines total (6 face + name + status)
- ~15 chars wide
- Rendered in cyan (#00e5ff) matching TUI theme
- Positioned bottom-right of chat panel, above the input area

### 7 Expressions

Face swaps only — hair frame stays static for performance.

| State | Eyes | Mouth | Trigger |
|-------|------|-------|---------|
| Idle | `◕ ◕` | `◡` | Waiting for input |
| Thinking | `◕ ◕` | `─` | Processing/generating |
| Happy | `◕ ◕` | `◠` | Task succeeded, greeting |
| Concerned | `◕ ◕` | `╭╮` | Error, warning |
| Surprised | `○ ○` | `○` | Unexpected result |
| Focused | `▪ ▪` | `─` | Deep code analysis |
| Sleeping | `─ ─` | `z` | Idle >5min |

### Idle Animations

- **Blink**: Eyes swap to `─ ─` for 1 frame (~200ms), random interval 3-8 seconds
- **Hair sway**: Bottom `▓▓` shifts 1 char left/right occasionally (every 10-15 seconds)

### Status Text

One line below the name. Combines real engine state with personality flavor.

| Engine Event | Status Text |
|-------------|-------------|
| Ready/idle | `✦ ready` |
| User typing | `listening...` |
| Local inference | `hmm, thinking...` |
| Platform dispatch | `asking F.O.R.G.E. ✦` (or whichever agent) |
| KB search | `checking my notes...` |
| Code generation | `writing code...` |
| Success | `done! ◡` |
| Error | `oh no... let me retry` |
| Hub connecting | `connecting to hub...` |
| Hub offline | `flying solo ✦` |

Status text updates are driven by WebSocket message types already flowing through the TUI (intent, dispatch_target, errors).

## Architecture

### New File: `archie-tui/views/companion.go`

`CompanionView` Bubble Tea component:
- `State` enum: Idle, Thinking, Happy, Concerned, Surprised, Focused, Sleeping
- `StatusText` string: current status message
- `Render(width, height int) string`: returns the full companion block (face + name + status)
- `Update(msg tea.Msg) (CompanionView, tea.Cmd)`: handles state transitions from engine messages + timer ticks
- `blinkTick()` / `swayTick()`: timer commands for idle animations

### Integration into `model.go`

- `CompanionView` added to the model struct
- Rendered in `View()` alongside `ChatView` — chat takes left/center, companion takes bottom-right
- Lipgloss `Place()` for positioning

### State Transitions

Engine WebSocket messages already carry `type`, `intent`, `dispatch_target`. The companion maps these:

```
message received     → Thinking
response type        → check for error → Concerned, else Happy
dispatch_target=platform → status "asking {agent}..."
dispatch_target=local    → status "hmm, thinking..."
no message >5min     → Sleeping
session_create       → Happy + "hello! ◡"
```

## Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `archie-tui/views/companion.go` | CompanionView component |
| Modify | `archie-tui/model.go` | Add CompanionView to model, render in View() |
| Modify | `archie-tui/theme.go` | Add companion color style (cyan) |
| Modify | `archie-tui/messages.go` | Add companion state message types if needed |

## Testing

- **Visual**: Run TUI, verify companion renders in correct position
- **Expression**: Send different message types, verify face changes
- **Idle animation**: Wait 5+ seconds, verify blink occurs
- **Status text**: Verify status updates match engine state
- **Resize**: Verify companion repositions on terminal resize
- **Small terminal**: Companion hides if terminal width < 60 chars (don't break the chat)

## Future

- **Pixel Factory integration**: This character design can be exported as a sprite sheet for web/game use
- **Velxar visibility**: Capture Velxar's speech bubble and inject into Claude context when user references him
- **Mood sync**: When PersonalityBuilder has hub data, companion expression could reflect ARCHIE's actual mood from the platform
