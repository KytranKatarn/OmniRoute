# LCARS TUI Theming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply LCARS visual identity to the Go TUI — panel borders, header bar, elbow corners, and accent-colored segments matching the platform's sci-fi aesthetic.

**Architecture:** New `views/lcars.go` with reusable LCARS frame-rendering functions. Update `model.go` View() to wrap chat, status bar, and banner in LCARS frames. Pure styling — no logic changes.

**Tech Stack:** Go 1.24, Lipgloss (border styles, box model), Unicode box-drawing characters.

**Repo:** `/mnt/archie_brain/archie-code/archie-tui/`

---

### Task 1: Create LCARS frame rendering functions

**Files:**
- Create: `archie-tui/views/lcars.go`

- [ ] **Step 1: Create lcars.go with frame rendering**

```go
package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

var (
	lcarsAccent = lipgloss.Color("#00e5ff")
	lcarsDim    = lipgloss.Color("#1a1a2e")
	lcarsText   = lipgloss.Color("#e5e7eb")
	lcarsPurple = lipgloss.Color("#8b5cf6")
)

// LCARSPanel renders content inside an LCARS-styled panel with elbow corners.
// accent is the panel's accent color, title is shown in the header bar.
func LCARSPanel(content string, title string, accent lipgloss.Color, width int) string {
	if width < 20 {
		return content
	}

	accentStyle := lipgloss.NewStyle().Foreground(accent)
	dimStyle := lipgloss.NewStyle().Foreground(lcarsDim)
	titleStyle := lipgloss.NewStyle().Foreground(accent).Bold(true)

	innerWidth := width - 4 // 2 border + 2 padding

	// Top bar: elbow + colored segment + title
	titleText := titleStyle.Render(title)
	titleLen := lipgloss.Width(titleText)
	segmentLen := innerWidth - titleLen - 2
	if segmentLen < 0 {
		segmentLen = 0
	}
	segment := accentStyle.Render(strings.Repeat("━", segmentLen))

	topLeft := accentStyle.Render("╭━")
	topRight := accentStyle.Render("━╮")
	topBar := topLeft + segment + " " + titleText + " " + topRight

	// Bottom bar: elbow corners
	bottomSegment := accentStyle.Render(strings.Repeat("━", innerWidth))
	bottomLeft := accentStyle.Render("╰━")
	bottomRight := accentStyle.Render("━╯")
	bottomBar := bottomLeft + bottomSegment + bottomRight

	// Side borders
	borderStyle := accentStyle

	// Wrap content lines with side borders
	contentLines := strings.Split(content, "\n")
	var framedLines []string
	framedLines = append(framedLines, topBar)

	for _, line := range contentLines {
		lineWidth := lipgloss.Width(line)
		padding := ""
		if lineWidth < innerWidth {
			padding = strings.Repeat(" ", innerWidth-lineWidth)
		}
		framedLines = append(framedLines, borderStyle.Render("│")+" "+line+padding+" "+borderStyle.Render("│"))
	}

	framedLines = append(framedLines, bottomBar)

	return strings.Join(framedLines, "\n")
}

// LCARSHeader renders a standalone LCARS header bar with colored segment.
func LCARSHeader(title string, accent lipgloss.Color, width int) string {
	accentStyle := lipgloss.NewStyle().Foreground(accent).Bold(true)
	dimStyle := lipgloss.NewStyle().Background(accent).Foreground(lipgloss.Color("#0a0a0f"))

	// Elbow + segment + title
	titleText := " " + title + " "
	segLen := width - lipgloss.Width(titleText) - 4
	if segLen < 0 {
		segLen = 0
	}

	elbow := accentStyle.Render("╭━")
	seg := accentStyle.Render(strings.Repeat("━", segLen))
	label := dimStyle.Render(titleText)

	return elbow + seg + label + accentStyle.Render("━╮")
}

// LCARSStatusBar renders a bottom status bar with LCARS elbow corners.
func LCARSStatusBar(content string, accent lipgloss.Color, width int) string {
	accentStyle := lipgloss.NewStyle().Foreground(accent)

	contentWidth := lipgloss.Width(content)
	padLen := width - contentWidth - 4
	if padLen < 0 {
		padLen = 0
	}

	left := accentStyle.Render("╰━")
	right := accentStyle.Render("━╯")
	pad := strings.Repeat(" ", padLen)

	return left + " " + content + pad + " " + right
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build ./views/`
Expected: no errors (note: `dimStyle` may show as unused — remove if so)

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/views/lcars.go
git commit -m "feat(tui): add LCARS frame rendering functions"
```

---

### Task 2: Apply LCARS framing to the TUI layout

**Files:**
- Modify: `archie-tui/model.go`
- Modify: `archie-tui/theme.go`

- [ ] **Step 1: Update View() to use LCARS panels**

Read the current `model.go` View() method first. Then replace it with LCARS-wrapped version.

The changes:
1. Replace the plain banner with `views.LCARSHeader("A.R.C.H.I.E. Code CLI", views.LCARSAccent(), m.width)` — expose `LCARSAccent()` as a getter or use the accent color directly from theme.go
2. Wrap the chat content in `views.LCARSPanel(chatContent, "COMMS", ColorCyan, chatWidth)` — the chat panel gets a frame
3. Replace the status bar rendering with `views.LCARSStatusBar(statusContent, ColorCyan, m.width)` — bottom bar gets elbows

The overall layout structure becomes:
```
╭━━━━━━━━━━━━━━━━ A.R.C.H.I.E. Code CLI ━╮  ← LCARS header
│                                           │
│  Chat content...                    Face  │  ← LCARS panel + companion
│                                           │
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯
❯ input area
╰━ HUB | git:main | archie:7b              ━╯  ← LCARS status bar
```

Implementation approach for View():

```go
func (m model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	// LCARS header
	header := views.LCARSHeader("A.R.C.H.I.E. Code CLI", ColorCyan, m.width)

	// Chat content with companion
	chatContent := m.chat.Render()
	companionBlock := m.companion.Render()

	var mainPanel string
	if companionBlock != "" {
		companionWidth := 20
		chatWidth := m.width - companionWidth - 6 // account for panel borders
		if chatWidth < 40 {
			mainPanel = views.LCARSPanel(chatContent, "COMMS", ColorCyan, m.width)
		} else {
			chatStyled := lipgloss.NewStyle().Width(chatWidth).Render(chatContent)
			companionStyled := lipgloss.NewStyle().Width(companionWidth).Render(companionBlock)
			combined := lipgloss.JoinHorizontal(lipgloss.Bottom, chatStyled, companionStyled)
			mainPanel = views.LCARSPanel(combined, "COMMS", ColorCyan, m.width)
		}
	} else {
		mainPanel = views.LCARSPanel(chatContent, "COMMS", ColorCyan, m.width)
	}

	// Skill picker overlay (if visible)
	var skillSection string
	if m.skillPicker.Visible {
		skillSection = m.skillPicker.Render()
	}

	// Input area
	inputLine := lipgloss.NewStyle().Padding(0, 1).Render(m.input.View())

	// LCARS status bar
	statusContent := m.statusBar.RenderContent() // need a new method that returns just the content string
	statusBar := views.LCARSStatusBar(statusContent, ColorCyan, m.width)

	// Assemble
	var sections []string
	sections = append(sections, header)
	sections = append(sections, mainPanel)
	if skillSection != "" {
		sections = append(sections, skillSection)
	}

	mainContent := strings.Join(sections, "\n")
	mainLines := strings.Count(mainContent, "\n") + 1
	if mainLines < m.height-3 {
		mainContent += strings.Repeat("\n", m.height-3-mainLines)
	}

	return mainContent + "\n" + inputLine + "\n" + statusBar
}
```

- [ ] **Step 2: Add RenderContent() method to StatusBar**

In `views/status.go`, add a method that returns just the inner content string (without the background wrapper) so the LCARS status bar can wrap it:

```go
// RenderContent returns the status bar content without background styling.
func (s *StatusBar) RenderContent() string {
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

	return content
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go build .`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie-tui/model.go archie-tui/views/status.go archie-tui/views/lcars.go
git commit -m "feat(tui): apply LCARS framing to TUI layout — panels, headers, elbows"
```

---

### Task 3: Verify and push

**Files:** None

- [ ] **Step 1: Run go vet**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && go vet ./...`
Expected: no issues

- [ ] **Step 2: Push to GitHub**

```bash
cd /mnt/archie_brain/archie-code
git push origin main
```

- [ ] **Step 3: Complete platform task**

Call `mcp__archie__complete_task` with task_id 1618.
