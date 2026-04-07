# ASCII Companion Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an ASCII companion widget (CompanionView) in the Go TUI that shows ARCHIE's face with 7 expressions, idle animations, and status text driven by engine WebSocket messages.

**Architecture:** New `views/companion.go` Bubble Tea component with a state machine for expressions, timer-driven blink/sway animations, and Lipgloss styling in cyan. Integrated into `model.go` as a bottom-right overlay alongside the existing ChatView. Hides on small terminals (<60 chars).

**Tech Stack:** Go 1.24, Bubble Tea (bubbletea v1.3.10), Lipgloss (v1.1.0), existing WebSocket message types.

**Repo:** `/mnt/archie_brain/archie-code/` — TUI at `archie-tui/`, engine at `archie_engine/`

**Spec:** `docs/superpowers/specs/2026-04-03-archie-code-ascii-companion-design.md`

---

### Task 1: CompanionView data types and state enum

**Files:**
- Create: `archie-tui/views/companion.go`

- [ ] **Step 1: Create companion.go with state enum and struct**

```go
package views

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// CompanionState represents the current expression.
type CompanionState int

const (
	StateIdle CompanionState = iota
	StateThinking
	StateHappy
	StateConcerned
	StateSurprised
	StateFocused
	StateSleeping
)

// CompanionView is the ASCII companion widget.
type CompanionView struct {
	State      CompanionState
	StatusText string
	blinking   bool
	swayRight  bool
	lastInput  time.Time
	Width      int
	Height     int
}

// NewCompanionView creates a companion in idle state.
func NewCompanionView() *CompanionView {
	return &CompanionView{
		State:      StateIdle,
		StatusText: "✦ ready",
		lastInput:  time.Now(),
	}
}

// BlinkTickMsg triggers a blink animation frame.
type BlinkTickMsg struct{}

// BlinkEndMsg ends the blink animation frame.
type BlinkEndMsg struct{}

// SwayTickMsg triggers a hair sway animation.
type SwayTickMsg struct{}

// SleepCheckMsg checks if companion should sleep.
type SleepCheckMsg struct{}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build ./views/`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/views/companion.go
git commit -m "feat(tui): add CompanionView data types and state enum"
```

---

### Task 2: Face rendering with 7 expressions

**Files:**
- Modify: `archie-tui/views/companion.go`

- [ ] **Step 1: Add the face rendering method**

Append to `companion.go`:

```go
import (
	"fmt"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// expression returns eyes and mouth for the current state.
func (c *CompanionView) expression() (eyes, mouth string) {
	if c.blinking {
		return "─ ─", "◡"
	}
	switch c.State {
	case StateThinking:
		return "◕ ◕", "─"
	case StateHappy:
		return "◕ ◕", "◠"
	case StateConcerned:
		return "◕ ◕", "╭╮"
	case StateSurprised:
		return "○ ○", "○"
	case StateFocused:
		return "▪ ▪", "─"
	case StateSleeping:
		return "─ ─", "z"
	default: // Idle
		return "◕ ◕", "◡"
	}
}

// Render returns the full companion block as a styled string.
// Returns empty string if width < 60 (don't break the chat).
func (c *CompanionView) Render() string {
	if c.Width < 60 {
		return ""
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))

	eyes, mouth := c.expression()

	// Hair sway: bottom hair shifts 1 char
	bottomLeft := "▓▓"
	bottomRight := "▓▓"
	if c.swayRight {
		bottomLeft = " ▓▓"
		bottomRight = "▓▓"
	}

	face := []string{
		"    ╭───╮    ",
		"   ╱▓▓▓▓▓╲   ",
		"  │▓╭───╮▓│  ",
		fmt.Sprintf("  │▓│%s│▓│  ", eyes),
		fmt.Sprintf("  ╰─│ %s │─╯  ", mouth),
		"   ▓╰───╯▓   ",
		fmt.Sprintf("   %s   %s   ", bottomLeft, bottomRight),
	}

	var lines []string
	for _, line := range face {
		lines = append(lines, cyan.Render(line))
	}
	lines = append(lines, cyan.Bold(true).Render("  A.R.C.H.I.E.  "))
	lines = append(lines, dim.Render(fmt.Sprintf("   %s", c.StatusText)))

	return strings.Join(lines, "\n")
}
```

Note: The imports at top of file need to be consolidated — the file will have one `import` block with all packages: `fmt`, `strings`, `time`, `tea`, `lipgloss`.

- [ ] **Step 2: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build ./views/`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/views/companion.go
git commit -m "feat(tui): add companion face rendering with 7 expressions"
```

---

### Task 3: Timer commands for blink and sway animations

**Files:**
- Modify: `archie-tui/views/companion.go`

- [ ] **Step 1: Add timer command functions and Update method**

Append to `companion.go`:

```go
import (
	"math/rand"
)

// BlinkCmd returns a command that triggers a blink after a random interval (3-8s).
func BlinkCmd() tea.Cmd {
	delay := time.Duration(3+rand.Intn(6)) * time.Second
	return tea.Tick(delay, func(t time.Time) tea.Msg {
		return BlinkTickMsg{}
	})
}

// blinkEndCmd returns a command that ends the blink after 200ms.
func blinkEndCmd() tea.Cmd {
	return tea.Tick(200*time.Millisecond, func(t time.Time) tea.Msg {
		return BlinkEndMsg{}
	})
}

// SwayCmd returns a command that triggers hair sway after 10-15s.
func SwayCmd() tea.Cmd {
	delay := time.Duration(10+rand.Intn(6)) * time.Second
	return tea.Tick(delay, func(t time.Time) tea.Msg {
		return SwayTickMsg{}
	})
}

// SleepCheckCmd returns a command that checks for sleep after 5 minutes.
func SleepCheckCmd() tea.Cmd {
	return tea.Tick(5*time.Minute, func(t time.Time) tea.Msg {
		return SleepCheckMsg{}
	})
}

// Update handles animation ticks and state transitions.
func (c *CompanionView) Update(msg tea.Msg) tea.Cmd {
	switch msg.(type) {
	case BlinkTickMsg:
		if c.State != StateSleeping {
			c.blinking = true
			return blinkEndCmd()
		}
	case BlinkEndMsg:
		c.blinking = false
		return BlinkCmd()
	case SwayTickMsg:
		c.swayRight = !c.swayRight
		return SwayCmd()
	case SleepCheckMsg:
		if time.Since(c.lastInput) > 5*time.Minute && c.State != StateSleeping {
			c.State = StateSleeping
			c.StatusText = "zzz..."
		}
		return SleepCheckCmd()
	}
	return nil
}

// SetState sets the companion state and updates the last input time.
func (c *CompanionView) SetState(state CompanionState, status string) {
	c.State = state
	c.StatusText = status
	c.lastInput = time.Now()
}
```

Note: Consolidate the `import` block at the top of the file — add `"math/rand"` to the existing imports.

- [ ] **Step 2: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build ./views/`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/views/companion.go
git commit -m "feat(tui): add companion blink/sway animation timers"
```

---

### Task 4: Add companion message types to messages.go

**Files:**
- Modify: `archie-tui/messages.go`

The existing `EngineResponseMsg` already carries `Type`, `Intent`, and `Content`. We need to add `DispatchTarget` so the companion knows when platform dispatch happens.

- [ ] **Step 1: Add DispatchTarget field to EngineResponseMsg**

In `messages.go`, add the field to `EngineResponseMsg`:

```go
type EngineResponseMsg struct {
	Type           string   `json:"type"`
	SessionID      string   `json:"session_id"`
	Content        string   `json:"content"`
	Intent         string   `json:"intent"`
	ToolCalls      []string `json:"tool_calls"`
	HubStatus      string   `json:"hub_status"`
	NodeID         string   `json:"node_id"`
	Skills         []Skill  `json:"skills"`
	DispatchTarget string   `json:"dispatch_target"`
}
```

- [ ] **Step 2: Parse dispatch_target in model.go listenCmd**

In `model.go`, inside the `listenCmd()` function, add parsing after the existing fields (after line 88):

```go
		resp := EngineResponseMsg{
			Type:           getString(raw, "type"),
			SessionID:      getString(raw, "session_id"),
			Content:        getString(raw, "content"),
			Intent:         getString(raw, "intent"),
			HubStatus:      getString(raw, "hub_status"),
			NodeID:         getString(raw, "node_id"),
			DispatchTarget: getString(raw, "dispatch_target"),
		}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build .`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/messages.go archie-tui/model.go
git commit -m "feat(tui): add DispatchTarget field for companion state mapping"
```

---

### Task 5: Integrate CompanionView into model.go

**Files:**
- Modify: `archie-tui/model.go`
- Modify: `archie-tui/theme.go`

- [ ] **Step 1: Add CompanionView to the model struct and initialModel**

In `model.go`, add the field to the `model` struct:

```go
type model struct {
	input       textinput.Model
	chat        *views.ChatView
	statusBar   *views.StatusBar
	skillPicker *views.SkillPicker
	companion   *views.CompanionView
	client      *Client
	sessionID   string
	width       int
	height      int
	connected   bool
	err         error
}
```

In `initialModel`, add:

```go
	return model{
		input:       ti,
		chat:        views.NewChatView(),
		statusBar:   views.NewStatusBar(),
		skillPicker: views.NewSkillPicker(),
		companion:   views.NewCompanionView(),
		client:      NewClient(wsURL),
	}
```

- [ ] **Step 2: Start animation timers in Init**

Update `Init()`:

```go
func (m model) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.connectCmd(),
		views.BlinkCmd(),
		views.SwayCmd(),
		views.SleepCheckCmd(),
	)
}
```

- [ ] **Step 3: Wire companion Update in the model Update function**

In `Update()`, add companion animation handling. Insert before the final `var cmd tea.Cmd` block (before line 217):

```go
	// Companion animation ticks
	case views.BlinkTickMsg, views.BlinkEndMsg, views.SwayTickMsg, views.SleepCheckMsg:
		cmd := m.companion.Update(msg)
		return m, cmd
```

This goes inside the main `switch msg := msg.(type)` block.

- [ ] **Step 4: Map EngineResponseMsg to companion states**

Inside the `case EngineResponseMsg:` block in `Update()`, add companion state mapping after the existing switch cases (after line 212, before `return m, m.listenCmd()`):

```go
		// Update companion state based on engine message
		switch msg.Type {
		case "response":
			if strings.Contains(msg.Content, "error") || strings.Contains(msg.Content, "Error") {
				m.companion.SetState(views.StateConcerned, "oh no... let me retry")
			} else {
				m.companion.SetState(views.StateHappy, "done! ◡")
			}
		case "session_created":
			m.companion.SetState(views.StateHappy, "hello! ◡")
		case "hub_status":
			if msg.HubStatus == "connected" {
				m.companion.SetState(views.StateIdle, "✦ ready")
			} else {
				m.companion.SetState(views.StateIdle, "flying solo ✦")
			}
		case "error":
			m.companion.SetState(views.StateConcerned, "oh no... let me retry")
		}
		if msg.DispatchTarget == "platform" {
			m.companion.SetState(views.StateThinking, "asking the crew ✦")
		} else if msg.DispatchTarget == "local" {
			m.companion.SetState(views.StateThinking, "hmm, thinking...")
		}
```

Also, when the user sends a message (the `"enter"` key handler), set the companion to thinking. After `_ = m.client.SendMessage(val, m.sessionID)` (line 139):

```go
				m.companion.SetState(views.StateThinking, "hmm, thinking...")
```

- [ ] **Step 5: Update WindowSizeMsg to set companion dimensions**

Inside the `case tea.WindowSizeMsg:` block, add:

```go
		m.companion.Width = msg.Width
		m.companion.Height = msg.Height
```

- [ ] **Step 6: Render companion in View()**

Replace the `View()` method to position the companion bottom-right of the chat area:

```go
func (m model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	var sections []string

	banner := BannerStyle.Render("  A.R.C.H.I.E. Code CLI")
	sections = append(sections, banner, "")

	chatContent := m.chat.Render()

	// Render companion overlay to the right of chat
	companionBlock := m.companion.Render()
	if companionBlock != "" {
		companionWidth := 20
		chatWidth := m.width - companionWidth - 2
		if chatWidth < 40 {
			chatWidth = m.width
			companionBlock = ""
		}
		if companionBlock != "" {
			chatStyled := lipgloss.NewStyle().Width(chatWidth).Render(chatContent)
			companionStyled := lipgloss.NewStyle().Width(companionWidth).Render(companionBlock)
			combined := lipgloss.JoinHorizontal(lipgloss.Bottom, chatStyled, companionStyled)
			sections = append(sections, combined)
		} else {
			sections = append(sections, chatContent)
		}
	} else {
		sections = append(sections, chatContent)
	}

	if m.skillPicker.Visible {
		sections = append(sections, m.skillPicker.Render())
	}

	mainContent := strings.Join(sections, "\n")
	mainLines := strings.Count(mainContent, "\n") + 1
	if mainLines < m.height-3 {
		mainContent += strings.Repeat("\n", m.height-3-mainLines)
	}

	inputLine := lipgloss.NewStyle().Padding(0, 1).Render(m.input.View())
	status := m.statusBar.Render()

	return mainContent + "\n" + inputLine + "\n" + status
}
```

- [ ] **Step 7: Add CompanionStyle to theme.go**

In `theme.go`, add:

```go
	CompanionFaceStyle   = lipgloss.NewStyle().Foreground(ColorCyan)
	CompanionNameStyle   = lipgloss.NewStyle().Foreground(ColorCyan).Bold(true)
	CompanionStatusStyle = lipgloss.NewStyle().Foreground(ColorDim)
```

(These are available for companion.go to import if it wants shared styles later, but companion.go currently uses inline styles for self-containment.)

- [ ] **Step 8: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build .`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/model.go archie-tui/theme.go
git commit -m "feat(tui): integrate CompanionView — face, animations, state mapping"
```

---

### Task 6: Manual visual testing

**Files:** None (testing only)

- [ ] **Step 1: Build the TUI**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build -o archie-tui .`
Expected: binary created

- [ ] **Step 2: Start the engine**

Run: `cd /mnt/archie_brain/archie-code && source .venv/bin/activate && OLLAMA_HOST=http://192.168.1.200:11434 python -m archie_engine &`
Expected: engine starts on ws://127.0.0.1:9090

- [ ] **Step 3: Run the TUI and verify companion appears**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && ./archie-tui`

Verify:
- Companion face renders bottom-right of chat area
- "A.R.C.H.I.E." name label below face
- "✦ ready" status text below name
- Face is cyan colored

- [ ] **Step 4: Test expression changes**

Type a message and press enter. Verify:
- Companion goes to Thinking ("hmm, thinking...")
- When response arrives, companion goes to Happy ("done! ◡")

- [ ] **Step 5: Test blink animation**

Wait 3-8 seconds idle. Verify:
- Eyes briefly flash to `─ ─` then back to normal

- [ ] **Step 6: Test small terminal**

Resize terminal to <60 chars wide. Verify:
- Companion disappears (no layout break)
- Resize back, companion reappears

- [ ] **Step 7: Commit any fixes found during testing**

If fixes were needed:
```bash
cd /mnt/archie_brain/archie-code
git add -A
git commit -m "fix(tui): companion visual testing fixes"
```

---

### Task 7: Final cleanup and push

**Files:** None

- [ ] **Step 1: Run go vet**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go vet ./...`
Expected: no issues

- [ ] **Step 2: Run existing Python tests to confirm no engine regressions**

Run: `cd /mnt/archie_brain/archie-code && source .venv/bin/activate && python -m pytest tests/ -q`
Expected: 222 tests pass (engine unchanged, so no regressions)

- [ ] **Step 3: Push to GitHub**

```bash
cd /mnt/archie_brain/archie-code
git push origin main
```

- [ ] **Step 4: Complete task in platform**

Call `mcp__archie__complete_task` with task_id 1617 and verification notes.
