package views

import (
	"fmt"
	"strings"

	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

var mdRenderer *glamour.TermRenderer

func init() {
	mdRenderer, _ = glamour.NewTermRenderer(
		glamour.WithStylePath("dark"),
		glamour.WithWordWrap(80),
	)
}

type ChatMessage struct {
	Role    string
	Content string
}

type ChatView struct {
	Messages []ChatMessage
	Width    int
	Height   int
}

func NewChatView() *ChatView {
	return &ChatView{Messages: []ChatMessage{}}
}

func (c *ChatView) AddMessage(role, content string) {
	c.Messages = append(c.Messages, ChatMessage{Role: role, Content: content})
}

// AppendToLast appends content to the last message (used for streaming tokens).
func (c *ChatView) AppendToLast(content string) {
	if len(c.Messages) > 0 {
		c.Messages[len(c.Messages)-1].Content += content
	}
}

// FinalizeLastMarkdown re-renders the last message content through glamour
// after streaming is complete, so the full markdown is properly formatted.
func (c *ChatView) FinalizeLastMarkdown() {
	// No-op needed — Render() already applies glamour per-message.
	// This method exists as an explicit signal that streaming is done
	// and can be extended for post-processing if needed.
}

func (c *ChatView) Render() string {
	if len(c.Messages) == 0 {
		dim := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
		return dim.Render("  No messages yet. Type a message or /command to begin.")
	}

	cyan := lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
	text := lipgloss.NewStyle().Foreground(lipgloss.Color("#e5e7eb"))
	dimStyle := lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280")).Italic(true)

	var lines []string
	for _, msg := range c.Messages {
		switch msg.Role {
		case "user":
			lines = append(lines, text.Render(fmt.Sprintf("  > %s", msg.Content)))
		case "assistant":
			if mdRenderer != nil {
				rendered, err := mdRenderer.Render(msg.Content)
				if err == nil {
					// Trim trailing newlines glamour adds, indent each line
					rendered = strings.TrimRight(rendered, "\n")
					for _, rl := range strings.Split(rendered, "\n") {
						lines = append(lines, "  "+rl)
					}
				} else {
					lines = append(lines, cyan.Render(fmt.Sprintf("  %s", msg.Content)))
				}
			} else {
				lines = append(lines, cyan.Render(fmt.Sprintf("  %s", msg.Content)))
			}
		case "system":
			lines = append(lines, dimStyle.Render(fmt.Sprintf("  [%s]", msg.Content)))
		}
		lines = append(lines, "")
	}

	if c.Height > 0 && len(lines) > c.Height {
		lines = lines[len(lines)-c.Height:]
	}

	return strings.Join(lines, "\n")
}
