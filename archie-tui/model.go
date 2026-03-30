package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/KytranKatarn/archie-tui/views"
)

const asciiBanner = `
   ╔═══════════════════════════════════════════════════════════╗
   ║                                                           ║
   ║    █████╗ ██████╗  ██████╗██╗  ██╗██╗███████╗            ║
   ║   ██╔══██╗██╔══██╗██╔════╝██║  ██║██║██╔════╝            ║
   ║   ███████║██████╔╝██║     ███████║██║█████╗              ║
   ║   ██╔══██║██╔══██╗██║     ██╔══██║██║██╔══╝              ║
   ║   ██║  ██║██║  ██║╚██████╗██║  ██║██║███████╗            ║
   ║   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝╚══════╝            ║
   ║                                                           ║
   ║          C O D E   C L I   v0.1.0                         ║
   ║          AI-Powered Development Terminal                  ║
   ║                                                           ║
   ╚═══════════════════════════════════════════════════════════╝`

type model struct {
	input       textinput.Model
	spinner     spinner.Model
	chat        *views.ChatView
	statusBar   *views.StatusBar
	skillPicker *views.SkillPicker
	diffReview  *views.DiffReviewView
	client      *Client
	msgChan     chan EngineResponseMsg
	streamChan  chan interface{}
	sessionID   string
	width       int
	height      int
	connected   bool
	thinking    bool
	streaming   bool
	booting     bool
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

	sp := spinner.New()
	sp.Spinner = spinner.Spinner{
		Frames: []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"},
		FPS:    80 * time.Millisecond,
	}
	sp.Style = lipgloss.NewStyle().Foreground(ColorCyan)

	ch := make(chan EngineResponseMsg, 64)
	sch := make(chan interface{}, 256)

	return model{
		input:       ti,
		spinner:     sp,
		chat:        views.NewChatView(),
		statusBar:   views.NewStatusBar(),
		skillPicker: views.NewSkillPicker(),
		diffReview:  views.NewDiffReviewView(),
		client:      NewClient(wsURL),
		msgChan:     ch,
		streamChan:  sch,
		booting:     true,
	}
}

func (m model) Init() tea.Cmd {
	return tea.Batch(
		textinput.Blink,
		m.spinner.Tick,
		m.connectCmd(),
	)
}

// waitForEngine listens on the channel for incoming WebSocket messages
func waitForEngine(ch chan EngineResponseMsg) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

// waitForStream listens on the stream channel for streaming tokens
func waitForStream(ch chan interface{}) tea.Cmd {
	return func() tea.Msg {
		return <-ch
	}
}

func (m model) connectCmd() tea.Cmd {
	ch := m.msgChan
	sch := m.streamChan
	return func() tea.Msg {
		client := NewClient(m.client.url)

		// Wire onMessage to push into the channel
		client.SetOnMessage(func(raw map[string]interface{}) {
			msgType, _ := raw["type"].(string)

			// Route streaming messages to the stream channel
			if msgType == "stream_token" {
				content, _ := raw["content"].(string)
				done, _ := raw["done"].(bool)
				sessionID, _ := raw["session_id"].(string)
				sch <- StreamTokenMsg{Content: content, Done: done, SessionID: sessionID}
				return
			}
			if msgType == "stream_start" {
				sessionID, _ := raw["session_id"].(string)
				sch <- StreamStartMsg{SessionID: sessionID}
				return
			}

			data, _ := json.Marshal(raw)
			var msg EngineResponseMsg
			_ = json.Unmarshal(data, &msg)
			if t, ok := raw["type"].(string); ok {
				msg.Type = t
			}
			if c, ok := raw["content"].(string); ok {
				msg.Content = c
			}
			if s, ok := raw["session_id"].(string); ok {
				msg.SessionID = s
			}
			if h, ok := raw["hub_status"].(string); ok {
				msg.HubStatus = h
			}
			if n, ok := raw["node_id"].(string); ok {
				msg.NodeID = n
			}
			if skills, ok := raw["skills"].([]interface{}); ok {
				for _, s := range skills {
					if sm, ok := s.(map[string]interface{}); ok {
						msg.Skills = append(msg.Skills, Skill{
							Name:        fmt.Sprintf("%v", sm["name"]),
							Description: fmt.Sprintf("%v", sm["description"]),
						})
					}
				}
			}
			ch <- msg
		})

		err := client.Connect()
		if err != nil {
			return DisconnectedMsg{Err: err}
		}

		_ = client.Send(map[string]interface{}{
			"type":        "session_create",
			"working_dir": ".",
		})
		_ = client.Send(map[string]interface{}{"type": "list_skills"})
		_ = client.Send(map[string]interface{}{"type": "hub_status"})

		return ConnectedMsg{Client: client}
	}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		// ── Diff review mode intercepts all keys ──
		if m.diffReview.Visible {
			switch msg.String() {
			case "a":
				if err := m.diffReview.Accept(); err != nil {
					m.chat.AddMessage("system", fmt.Sprintf("Accept failed: %v", err))
				}
				if m.diffReview.Done() {
					m.chat.AddMessage("system", m.diffReview.SummaryMessage())
				}
			case "r":
				m.diffReview.Reject()
				if m.diffReview.Done() {
					m.chat.AddMessage("system", m.diffReview.SummaryMessage())
				}
			case "e":
				// Launch $EDITOR — must suspend Bubble Tea, then resume
				return m, tea.ExecProcess(buildEditorCmd(m.diffReview), func(err error) tea.Msg {
					return DiffEditorDoneMsg{Err: err}
				})
			case "n":
				if !m.diffReview.Done() {
					m.diffReview.Accept() // treat n as accept-and-next for convenience
					if m.diffReview.Done() {
						m.chat.AddMessage("system", m.diffReview.SummaryMessage())
					}
				}
			case "p":
				// Previous: go back one if possible
				if m.diffReview.Current > 0 {
					m.diffReview.Current--
				}
			case "up", "k":
				m.diffReview.ScrollUp()
			case "down", "j":
				m.diffReview.ScrollDown()
			case "q", "esc":
				m.diffReview.Visible = false
				m.chat.AddMessage("system", "Diff review cancelled.")
			}
			return m, nil
		}

		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			m.client.Close()
			return m, tea.Quit
		case "enter":
			if m.skillPicker.Visible {
				filtered := m.skillPicker.Filtered()
				if len(filtered) > 0 && m.skillPicker.Selected < len(filtered) {
					skill := filtered[m.skillPicker.Selected]
					m.input.SetValue("/" + skill.Name + " ")
					m.skillPicker.Visible = false
				}
				return m, nil
			}
			val := strings.TrimSpace(m.input.Value())
			if val == "" {
				return m, nil
			}
			m.chat.AddMessage("user", val)
			m.input.SetValue("")
			if m.connected {
				m.thinking = true
				_ = m.client.SendMessage(val, m.sessionID)
			} else {
				m.chat.AddMessage("system", "Not connected to engine")
			}
			return m, nil
		case "esc":
			if m.skillPicker.Visible {
				m.skillPicker.Visible = false
				return m, nil
			}
		case "tab":
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
		m.chat.Height = msg.Height - 6
		m.statusBar.Width = msg.Width
		m.skillPicker.Width = msg.Width
		m.skillPicker.Height = msg.Height / 2

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		return m, cmd

	case ConnectedMsg:
		m.connected = true
		m.booting = false
		if msg.Client != nil {
			m.client = msg.Client
		}
		m.chat.AddMessage("system", "Connected to ARCHIE Engine")
		return m, tea.Batch(waitForEngine(m.msgChan), waitForStream(m.streamChan))

	case DisconnectedMsg:
		m.connected = false
		m.booting = false
		if msg.Err != nil {
			m.chat.AddMessage("system", fmt.Sprintf("Engine not running: %v", msg.Err))
			m.chat.AddMessage("system", "Start engine: python -m archie_engine")
		}

	case StreamStartMsg:
		m.thinking = false
		m.streaming = true
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}
		// Add an empty assistant message that we'll append tokens to
		m.chat.AddMessage("assistant", "")
		return m, waitForStream(m.streamChan)

	case StreamTokenMsg:
		if msg.SessionID != "" {
			m.sessionID = msg.SessionID
		}
		if msg.Content != "" {
			m.chat.AppendToLast(msg.Content)
		}
		if msg.Done {
			m.streaming = false
			m.chat.FinalizeLastMarkdown()
			// Check if AI response contains code blocks with file paths
			if len(m.chat.Messages) > 0 {
				last := m.chat.Messages[len(m.chat.Messages)-1]
				if last.Role == "assistant" {
					changes := views.ParseCodeChanges(last.Content)
					if len(changes) > 0 {
						return m, func() tea.Msg { return DiffReviewMsg{Response: last.Content} }
					}
				}
			}
			return m, waitForStream(m.streamChan)
		}
		return m, waitForStream(m.streamChan)

	case DiffReviewMsg:
		changes := views.ParseCodeChanges(msg.Response)
		if len(changes) > 0 {
			m.diffReview.Width = m.width
			m.diffReview.Height = m.height
			m.diffReview.Load(changes)
			noun := "change"
			if len(changes) > 1 {
				noun = "changes"
			}
			m.chat.AddMessage("system", fmt.Sprintf(
				"AI suggested %d file %s. Press [a]ccept / [r]eject / [e]dit / [q]uit.",
				len(changes), noun,
			))
		}
		return m, waitForStream(m.streamChan)

	case DiffEditorDoneMsg:
		// $EDITOR subprocess finished — mark the change as edited and advance
		if msg.Err != nil {
			m.chat.AddMessage("system", fmt.Sprintf("Editor error: %v", msg.Err))
		} else {
			ch := m.diffReview.CurrentChange()
			if ch != nil {
				m.diffReview.Results = append(m.diffReview.Results, views.DiffResult{
					FilePath: ch.FilePath,
					Action:   "edited",
				})
				m.diffReview.Current++
				if m.diffReview.Done() {
					m.diffReview.Visible = false
					m.chat.AddMessage("system", m.diffReview.SummaryMessage())
				}
			}
		}
		return m, nil

	case EngineResponseMsg:
		m.thinking = false
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
		return m, waitForEngine(m.msgChan)
	}

	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	return m, cmd
}

// buildEditorCmd writes the current diff change to a temp file and returns
// an *exec.Cmd that opens it in $EDITOR, for use with tea.ExecProcess.
func buildEditorCmd(d *views.DiffReviewView) *exec.Cmd {
	ch := d.CurrentChange()
	if ch == nil {
		editor := os.Getenv("EDITOR")
		if editor == "" {
			editor = "vi"
		}
		return exec.Command(editor, "/dev/null")
	}

	ext := "txt"
	if ch.Lang != "" {
		ext = ch.Lang
	} else if idx := strings.LastIndex(ch.FilePath, "."); idx >= 0 {
		ext = ch.FilePath[idx+1:]
	}

	tmp, err := os.CreateTemp("", "archie-diff-*."+ext)
	if err == nil {
		_, _ = tmp.WriteString(ch.Content)
		tmp.Close()
		// Store the temp path in the change so DiffEditorDoneMsg can read it back
		d.Changes[d.Current].Content = tmp.Name() // temporarily holds temp path
	}

	editor := os.Getenv("EDITOR")
	if editor == "" {
		editor = "vi"
	}
	return exec.Command(editor, tmp.Name())
}

func (m model) View() string {
	if m.width == 0 {
		return "Loading..."
	}

	var sections []string

	// Show ASCII banner when booting or at start with few messages
	if m.booting || len(m.chat.Messages) == 0 {
		bannerStyle := lipgloss.NewStyle().Foreground(ColorCyan)
		sections = append(sections, bannerStyle.Render(asciiBanner))
		sections = append(sections, "")
	} else {
		banner := BannerStyle.Render("  A.R.C.H.I.E. Code CLI")
		sections = append(sections, banner, "")
	}

	// Chat area
	chatContent := m.chat.Render()
	sections = append(sections, chatContent)

	// Thinking/streaming indicator
	if m.thinking {
		thinkStyle := lipgloss.NewStyle().Foreground(ColorCyan).Italic(true)
		sections = append(sections, thinkStyle.Render(
			fmt.Sprintf("  %s ARCHIE is thinking...", m.spinner.View()),
		))
	} else if m.streaming {
		streamStyle := lipgloss.NewStyle().Foreground(ColorCyan).Italic(true)
		sections = append(sections, streamStyle.Render(
			fmt.Sprintf("  %s streaming...", m.spinner.View()),
		))
	}

	// Diff review overlay (takes priority over skill picker)
	if m.diffReview.Visible {
		sections = append(sections, m.diffReview.Render())
	} else if m.skillPicker.Visible {
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
