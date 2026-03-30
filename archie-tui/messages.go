package main

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

type Skill struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Source      string `json:"source"`
}

type StreamTokenMsg struct {
	Content   string
	Done      bool
	SessionID string
}

type StreamStartMsg struct {
	SessionID string
}

type ConnectedMsg struct {
	SessionID string
	Client    *Client
}

type DisconnectedMsg struct {
	Err error
}

type ErrorMsg struct {
	Err error
}

// DiffReviewMsg triggers opening the diff review panel with detected code changes.
type DiffReviewMsg struct {
	Response string // full AI response text to parse for code blocks
}

// DiffEditorDoneMsg is sent after the $EDITOR subprocess exits so Bubble Tea
// can reclaim the terminal.
type DiffEditorDoneMsg struct {
	Err error
}
