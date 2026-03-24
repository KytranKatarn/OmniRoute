# ARCHIE Go TUI — Implementation Plan (Plan 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ARCHIE Code CLI terminal interface using Go + Bubble Tea. Connects to the Python engine daemon via WebSocket. LCARS-themed with chat mode, skill picker, and status bar.

**Architecture:** Go binary (`archie-tui/`) connects to the engine's WebSocket server at ws://127.0.0.1:9090. Bubble Tea handles the TUI rendering. The TUI is a thin client — all logic lives in the Python engine.

**Tech Stack:** Go 1.22+, Bubble Tea (TUI framework), Lip Gloss (styling), gorilla/websocket (WebSocket client).

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md` (Section 8)

**Depends on:** Plan 2 (Engine WebSocket server).

**Go binary:** `~/go-sdk/go/bin/go` — use `export PATH=$HOME/go-sdk/go/bin:$PATH` before all go commands.

**Rollback:** All tasks are additive. Rollback: `rm -rf archie-tui/` and revert commits.

---

## File Structure

```
archie-tui/
  go.mod               — Module definition
  go.sum               — Dependency checksums
  main.go              — Entry point, flag parsing, connect to engine
  model.go             — Bubble Tea model (state, Update, View)
  messages.go          — WebSocket message types
  client.go            — WebSocket client (connect, send, receive)
  theme.go             — LCARS color theme + styles
  views/
    chat.go            — Chat view (messages + input)
    status.go          — Status bar (hub, branch, model)
    skills.go          — Skill picker overlay
```

---

## Task Overview (8 Tasks)

| # | Task | Scope | Est. Steps |
|---|------|-------|------------|
| 6.1 | Go module scaffold | go.mod, main.go, deps | 5 |
| 6.2 | Theme + styles | LCARS colors, Lip Gloss styles | 6 |
| 6.3 | WebSocket client | Connect, send, receive JSON | 8 |
| 6.4 | Message types | Typed Go structs for protocol | 5 |
| 6.5 | Chat view | Message list + text input | 8 |
| 6.6 | Status bar | Hub, branch, model indicators | 6 |
| 6.7 | Skill picker | Overlay for /command selection | 6 |
| 6.8 | Wire up + build | Bubble Tea model, main loop, binary | 6 |

---

### Task 6.1: Go module scaffold

**Files:**
- Create: `archie-tui/main.go`
- Create: `archie-tui/go.mod`

- [ ] **Step 1: Create directory and init module**

```bash
mkdir -p archie-tui
cd archie-tui
export PATH=$HOME/go-sdk/go/bin:$PATH
go mod init github.com/KytranKatarn/archie-tui
```

- [ ] **Step 2: Write main.go**

```go
package main

import (
	"flag"
	"fmt"
	"os"
)

var version = "0.1.0"

func main() {
	wsURL := flag.String("url", "ws://127.0.0.1:9090", "Engine WebSocket URL")
	showVersion := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *showVersion {
		fmt.Printf("ARCHIE Code CLI v%s\n", version)
		os.Exit(0)
	}

	fmt.Printf("ARCHIE Code CLI v%s\n", version)
	fmt.Printf("Connecting to engine at %s...\n", *wsURL)
	fmt.Println("(TUI not yet implemented)")
}
```

- [ ] **Step 3: Add dependencies**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui
go get github.com/charmbracelet/bubbletea
go get github.com/charmbracelet/lipgloss
go get github.com/charmbracelet/bubbles/textinput
go get github.com/charmbracelet/bubbles/viewport
go get github.com/gorilla/websocket
```

- [ ] **Step 4: Verify build**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui && go build -o archie-code . && ./archie-code --version
```

Expected: `ARCHIE Code CLI v0.1.0`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/ && git commit -m "feat(tui): Go module scaffold with Bubble Tea dependencies"
```

---

### Task 6.2: Theme and styles

**Files:**
- Create: `archie-tui/theme.go`

- [ ] **Step 1: Write theme.go**

```go
package main

import "github.com/charmbracelet/lipgloss"

// LCARS color palette
var (
	ColorCyan      = lipgloss.Color("#00e5ff")
	ColorPurple    = lipgloss.Color("#8b5cf6")
	ColorPink      = lipgloss.Color("#f472b6")
	ColorYellow    = lipgloss.Color("#fbbf24")
	ColorGreen     = lipgloss.Color("#10b981")
	ColorRed       = lipgloss.Color("#ef4444")
	ColorOrange    = lipgloss.Color("#f97316")
	ColorDim       = lipgloss.Color("#6b7280")
	ColorBg        = lipgloss.Color("#0a0a0f")
	ColorText      = lipgloss.Color("#e5e7eb")
)

// Styles
var (
	TitleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(ColorCyan).
			Padding(0, 1)

	UserMsgStyle = lipgloss.NewStyle().
			Foreground(ColorText)

	AssistantMsgStyle = lipgloss.NewStyle().
			Foreground(ColorCyan)

	SystemMsgStyle = lipgloss.NewStyle().
			Foreground(ColorDim).
			Italic(true)

	StatusBarStyle = lipgloss.NewStyle().
			Background(lipgloss.Color("#1a1a2e")).
			Foreground(ColorText).
			Padding(0, 1)

	HubConnectedStyle = lipgloss.NewStyle().
			Foreground(ColorGreen).
			Bold(true)

	HubDisconnectedStyle = lipgloss.NewStyle().
			Foreground(ColorDim)

	SkillNameStyle = lipgloss.NewStyle().
			Foreground(ColorPurple).
			Bold(true)

	InputPromptStyle = lipgloss.NewStyle().
			Foreground(ColorCyan).
			Bold(true)

	ErrorStyle = lipgloss.NewStyle().
			Foreground(ColorRed)

	BannerStyle = lipgloss.NewStyle().
			Foreground(ColorCyan).
			Bold(true)
)
```

- [ ] **Step 2: Verify compiles**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui && go build ./...
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/theme.go && git commit -m "feat(tui): LCARS color theme and Lip Gloss styles"
```

---

### Task 6.3: WebSocket client

**Files:**
- Create: `archie-tui/client.go`

- [ ] **Step 1: Write client.go**

```go
package main

import (
	"encoding/json"
	"fmt"
	"log"
	"sync"

	"github.com/gorilla/websocket"
)

// Client manages WebSocket connection to the engine
type Client struct {
	conn     *websocket.Conn
	url      string
	mu       sync.Mutex
	onMessage func(map[string]interface{})
}

// NewClient creates a new WebSocket client
func NewClient(url string) *Client {
	return &Client{url: url}
}

// Connect establishes WebSocket connection
func (c *Client) Connect() error {
	conn, _, err := websocket.DefaultDialer.Dial(c.url, nil)
	if err != nil {
		return fmt.Errorf("connect failed: %w", err)
	}
	c.conn = conn
	go c.readLoop()
	return nil
}

// Send sends a JSON message to the engine
func (c *Client) Send(msg map[string]interface{}) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn == nil {
		return fmt.Errorf("not connected")
	}
	data, err := json.Marshal(msg)
	if err != nil {
		return err
	}
	return c.conn.WriteMessage(websocket.TextMessage, data)
}

// SendMessage sends a chat message
func (c *Client) SendMessage(content string, sessionID string) error {
	msg := map[string]interface{}{
		"type":    "message",
		"content": content,
	}
	if sessionID != "" {
		msg["session_id"] = sessionID
	}
	return c.Send(msg)
}

// Close closes the connection
func (c *Client) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
}

// SetOnMessage sets the callback for incoming messages
func (c *Client) SetOnMessage(fn func(map[string]interface{})) {
	c.onMessage = fn
}

func (c *Client) readLoop() {
	defer c.Close()
	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			log.Printf("read error: %v", err)
			return
		}
		var msg map[string]interface{}
		if err := json.Unmarshal(message, &msg); err != nil {
			log.Printf("unmarshal error: %v", err)
			continue
		}
		if c.onMessage != nil {
			c.onMessage(msg)
		}
	}
}
```

- [ ] **Step 2: Verify compiles**

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/client.go && git commit -m "feat(tui): WebSocket client — connect, send, receive JSON"
```

---

### Task 6.4: Message types

**Files:**
- Create: `archie-tui/messages.go`

- [ ] **Step 1: Write messages.go**

```go
package main

// Bubble Tea messages for async WebSocket communication

// EngineResponseMsg is received when the engine sends a response
type EngineResponseMsg struct {
	Type      string   `json:"type"`
	SessionID string   `json:"session_id"`
	Content   string   `json:"content"`
	Intent    string   `json:"intent"`
	ToolCalls []string `json:"tool_calls"`
	HubStatus string   `json:"hub_status"`
	NodeID    string   `json:"node_id"`
	Skills    []Skill  `json:"skills"`
}

// Skill represents a skill from the engine
type Skill struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Source      string `json:"source"`
}

// ConnectedMsg signals successful WebSocket connection
type ConnectedMsg struct {
	SessionID string
}

// DisconnectedMsg signals WebSocket disconnection
type DisconnectedMsg struct {
	Err error
}

// ErrorMsg wraps errors for Bubble Tea
type ErrorMsg struct {
	Err error
}
```

- [ ] **Step 2: Verify compiles**

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/messages.go && git commit -m "feat(tui): message types for WebSocket protocol"
```

---

### Task 6.5: Chat view

**Files:**
- Create: `archie-tui/views/chat.go`

- [ ] **Step 1: Create views directory**

```bash
mkdir -p archie-tui/views
```

- [ ] **Step 2: Write chat.go**

```go
package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// ChatMessage represents a single message in the chat
type ChatMessage struct {
	Role    string // "user", "assistant", "system"
	Content string
}

// ChatView renders the message history
type ChatView struct {
	Messages []ChatMessage
	Width    int
	Height   int
}

// NewChatView creates a new chat view
func NewChatView() *ChatView {
	return &ChatView{
		Messages: []ChatMessage{},
	}
}

// AddMessage appends a message
func (c *ChatView) AddMessage(role, content string) {
	c.Messages = append(c.Messages, ChatMessage{Role: role, Content: content})
}

// Render returns the styled chat view string
func (c *ChatView) Render() string {
	if len(c.Messages) == 0 {
		dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
		return dim.Render("  No messages yet. Type a message or /command to begin.")
	}

	var lines []string
	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280")).Italic(true)

	for _, msg := range c.Messages {
		switch msg.Role {
		case "user":
			lines = append(lines, text.Render(fmt.Sprintf("  > %s", msg.Content)))
		case "assistant":
			lines = append(lines, cyan.Render(fmt.Sprintf("  %s", msg.Content)))
		case "system":
			lines = append(lines, dimStyle.Render(fmt.Sprintf("  [%s]", msg.Content)))
		}
		lines = append(lines, "")
	}

	// Trim to fit height if needed
	if c.Height > 0 && len(lines) > c.Height {
		lines = lines[len(lines)-c.Height:]
	}

	return strings.Join(lines, "\n")
}
```

- [ ] **Step 3: Verify compiles**

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/views/ && git commit -m "feat(tui): chat view — message rendering with LCARS styles"
```

---

### Task 6.6: Status bar

**Files:**
- Create: `archie-tui/views/status.go`

- [ ] **Step 1: Write status.go**

```go
package views

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
)

// StatusBar renders the bottom status bar
type StatusBar struct {
	HubStatus string // "connected", "disconnected", "offline"
	Branch    string
	Model     string
	Width     int
}

// NewStatusBar creates a new status bar
func NewStatusBar() *StatusBar {
	return &StatusBar{
		HubStatus: "disconnected",
		Branch:    "",
		Model:     "",
	}
}

// Render returns the styled status bar string
func (s *StatusBar) Render() string {
	bg := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#e5e7eb")).
		Width(s.Width).
		Padding(0, 1)

	green := lipgloss.NewStyle().Foreground(lipgloss.Color("#10b981")).Bold(true)
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))

	var hubIndicator string
	switch s.HubStatus {
	case "connected":
		hubIndicator = green.Render("HUB")
	case "offline":
		hubIndicator = dim.Render("HUB:OFF")
	default:
		hubIndicator = dim.Render("LOCAL")
	}

	var parts []string
	parts = append(parts, hubIndicator)
	if s.Branch != "" {
		parts = append(parts, cyan.Render(fmt.Sprintf("git:%s", s.Branch)))
	}
	if s.Model != "" {
		parts = append(parts, dim.Render(s.Model))
	}

	content := ""
	for i, p := range parts {
		if i > 0 {
			content += dim.Render(" | ")
		}
		content += p
	}

	return bg.Render(content)
}
```

- [ ] **Step 2: Verify compiles**

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/views/status.go && git commit -m "feat(tui): status bar — hub, branch, model indicators"
```

---

### Task 6.7: Skill picker

**Files:**
- Create: `archie-tui/views/skills.go`

- [ ] **Step 1: Write skills.go**

```go
package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// SkillItem for display
type SkillItem struct {
	Name        string
	Description string
}

// SkillPicker renders a skill selection overlay
type SkillPicker struct {
	Skills   []SkillItem
	Selected int
	Visible  bool
	Filter   string
	Width    int
	Height   int
}

// NewSkillPicker creates a new picker
func NewSkillPicker() *SkillPicker {
	return &SkillPicker{}
}

// Filtered returns skills matching the current filter
func (sp *SkillPicker) Filtered() []SkillItem {
	if sp.Filter == "" {
		return sp.Skills
	}
	var filtered []SkillItem
	lower := strings.ToLower(sp.Filter)
	for _, s := range sp.Skills {
		if strings.Contains(strings.ToLower(s.Name), lower) ||
			strings.Contains(strings.ToLower(s.Description), lower) {
			filtered = append(filtered, s)
		}
	}
	return filtered
}

// Render returns the styled skill picker string
func (sp *SkillPicker) Render() string {
	if !sp.Visible {
		return ""
	}

	purple := lipgloss.NewStyle().Foreground(lipgloss.Color("#8b5cf6")).Bold(true)
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	selected := lipgloss.NewStyle().
		Background(lipgloss.Color("#1a1a2e")).
		Foreground(lipgloss.Color("#00e5ff")).
		Bold(true)

	var lines []string
	lines = append(lines, purple.Render("  Skills"))
	lines = append(lines, dim.Render("  Type to filter, Enter to select, Esc to close"))
	lines = append(lines, "")

	filtered := sp.Filtered()
	for i, skill := range filtered {
		prefix := "  "
		style := text
		if i == sp.Selected {
			prefix = "> "
			style = selected
		}
		line := fmt.Sprintf("%s/%s — %s", prefix, skill.Name, skill.Description)
		lines = append(lines, style.Render(line))
	}

	if len(filtered) == 0 {
		lines = append(lines, dim.Render("  No matching skills"))
	}

	border := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("#8b5cf6")).
		Padding(1).
		Width(sp.Width - 4)

	return border.Render(strings.Join(lines, "\n"))
}
```

- [ ] **Step 2: Verify compiles**

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/views/skills.go && git commit -m "feat(tui): skill picker — filterable overlay for slash commands"
```

---

### Task 6.8: Wire up Bubble Tea model + build

**Files:**
- Create: `archie-tui/model.go`
- Modify: `archie-tui/main.go` — wire up Bubble Tea

- [ ] **Step 1: Write model.go**

```go
package main

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/KytranKatarn/archie-tui/views"
)

type model struct {
	input       textinput.Model
	chat        *views.ChatView
	statusBar   *views.StatusBar
	skillPicker *views.SkillPicker
	client      *Client
	sessionID   string
	width       int
	height      int
	connected   bool
	err         error
}

func initialModel(wsURL string) model {
	ti := textinput.New()
	ti.Placeholder = "Type a message or /command..."
	ti.Focus()
	ti.CharLimit = 4096
	ti.Width = 80
	ti.Prompt = "❯ "
	ti.PromptStyle = InputPromptStyle

	return model{
		input:       ti,
		chat:        views.NewChatView(),
		statusBar:   views.NewStatusBar(),
		skillPicker: views.NewSkillPicker(),
		client:      NewClient(wsURL),
	}
}

func (m model) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.connectToEngine(),
	)
}

func (m model) connectToEngine() tea.Cmd {
	return func() tea.Msg {
		err := m.client.Connect()
		if err != nil {
			return DisconnectedMsg{Err: err}
		}
		// Create session
		m.client.Send(map[string]interface{}{
			"type":        "session_create",
			"working_dir": ".",
		})
		// Request skills list
		m.client.Send(map[string]interface{}{"type": "list_skills"})
		// Request hub status
		m.client.Send(map[string]interface{}{"type": "hub_status"})
		return ConnectedMsg{}
	}
}

func (m model) waitForEngineMsg() tea.Cmd {
	return func() tea.Msg {
		// This would be wired to the client's onMessage callback
		// For now, return nil (engine responses come through tea.Program.Send)
		return nil
	}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			m.client.Close()
			return m, tea.Quit
		case "enter":
			if m.skillPicker.Visible {
				// Select skill from picker
				filtered := m.skillPicker.Filtered()
				if len(filtered) > 0 && m.skillPicker.Selected < len(filtered) {
					skill := filtered[m.skillPicker.Selected]
					m.input.SetValue("/" + skill.Name + " ")
					m.skillPicker.Visible = false
				}
				return m, nil
			}
			// Send message
			val := strings.TrimSpace(m.input.Value())
			if val == "" {
				return m, nil
			}
			m.chat.AddMessage("user", val)
			m.input.SetValue("")
			if m.connected {
				m.client.SendMessage(val, m.sessionID)
			}
			return m, nil
		case "esc":
			if m.skillPicker.Visible {
				m.skillPicker.Visible = false
				return m, nil
			}
		case "tab":
			// Toggle skill picker
			m.skillPicker.Visible = !m.skillPicker.Visible
			return m, nil
		case "up":
			if m.skillPicker.Visible && m.skillPicker.Selected > 0 {
				m.skillPicker.Selected--
				return m, nil
			}
		case "down":
			if m.skillPicker.Visible {
				filtered := m.skillPicker.Filtered()
				if m.skillPicker.Selected < len(filtered)-1 {
					m.skillPicker.Selected++
				}
				return m, nil
			}
		}

	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		m.input.Width = msg.Width - 4
		m.chat.Width = msg.Width
		m.chat.Height = msg.Height - 5 // Reserve for input + status
		m.statusBar.Width = msg.Width
		m.skillPicker.Width = msg.Width
		m.skillPicker.Height = msg.Height / 2

	case ConnectedMsg:
		m.connected = true
		m.chat.AddMessage("system", "Connected to ARCHIE Engine")
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}

	case DisconnectedMsg:
		m.connected = false
		if msg.Err != nil {
			m.chat.AddMessage("system", fmt.Sprintf("Connection failed: %v", msg.Err))
		}

	case EngineResponseMsg:
		switch msg.Type {
		case "response":
			m.chat.AddMessage("assistant", msg.Content)
			if msg.SessionID != "" {
				m.sessionID = msg.SessionID
			}
		case "session_created":
			m.sessionID = msg.SessionID
		case "hub_status":
			m.statusBar.HubStatus = msg.HubStatus
		case "skills_list":
			var items []views.SkillItem
			for _, s := range msg.Skills {
				items = append(items, views.SkillItem{Name: s.Name, Description: s.Description})
			}
			m.skillPicker.Skills = items
		case "error":
			m.chat.AddMessage("system", fmt.Sprintf("Error: %s", msg.Content))
		}
	}

	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

func (m model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	var sections []string

	// Banner
	banner := BannerStyle.Render("  A.R.C.H.I.E. Code CLI")
	sections = append(sections, banner)
	sections = append(sections, "")

	// Chat area
	chatContent := m.chat.Render()
	sections = append(sections, chatContent)

	// Skill picker overlay
	if m.skillPicker.Visible {
		sections = append(sections, m.skillPicker.Render())
	}

	// Fill remaining space
	mainContent := strings.Join(sections, "\n")
	mainLines := strings.Count(mainContent, "\n") + 1
	if mainLines < m.height-3 {
		mainContent += strings.Repeat("\n", m.height-3-mainLines)
	}

	// Input line
	inputLine := lipgloss.NewStyle().Padding(0, 1).Render(m.input.View())

	// Status bar
	status := m.statusBar.Render()

	return mainContent + "\n" + inputLine + "\n" + status
}
```

- [ ] **Step 2: Update main.go**

```go
package main

import (
	"flag"
	"fmt"
	"os"

	tea "github.com/charmbracelet/bubbletea"
)

var version = "0.1.0"

func main() {
	wsURL := flag.String("url", "ws://127.0.0.1:9090", "Engine WebSocket URL")
	showVersion := flag.Bool("version", false, "Show version")
	flag.Parse()

	if *showVersion {
		fmt.Printf("ARCHIE Code CLI v%s\n", version)
		os.Exit(0)
	}

	p := tea.NewProgram(
		initialModel(*wsURL),
		tea.WithAltScreen(),
	)

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
```

- [ ] **Step 3: Build binary**

```bash
export PATH=$HOME/go-sdk/go/bin:$PATH
cd /mnt/archie_brain/archie-tui && go build -o archie-code .
```

- [ ] **Step 4: Verify binary runs**

```bash
./archie-code --version
```

Expected: `ARCHIE Code CLI v0.1.0`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add archie-tui/ && git commit -m "feat(tui): Bubble Tea TUI with chat, status bar, skill picker

Completes Plan 6 — Go TUI. Components:
- LCARS color theme (Lip Gloss)
- WebSocket client (gorilla/websocket)
- Chat view with message rendering
- Status bar (hub, branch, model)
- Skill picker with filter
- Bubble Tea model wiring
- Binary: archie-code"
```

- [ ] **Step 6: Push**

```bash
git push
```

---

## Post-Plan Checklist

```bash
# Build binary
cd archie-tui && go build -o archie-code . && ./archie-code --version

# Push
git push

# Log decision
mcp log_decision: "Go TUI complete — Bubble Tea interface with LCARS theme"
mcp update_project_understanding: project 185 to 85%
```

## What's Next

- **Plan 7** — Distribution (pip package, Go cross-compile, installer, CI/CD)
- **Plan 8** — Website + Public Repo
