package views

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/charmbracelet/lipgloss"
)

// LCARS colors for diff
var (
	diffAddStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#a3e635"))
	diffDelStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#ff3b3b"))
	diffCtxStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("#6b7280"))
	diffHeaderStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff")).Bold(true)
	diffAcceptStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#a3e635")).Bold(true)
	diffRejectStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#ff3b3b")).Bold(true)
	diffEditStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("#fbbf24")).Bold(true)
	diffIndexStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("#8b5cf6"))
	diffBorderStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("#00e5ff"))
)

// CodeChange represents a single AI-suggested file change extracted from a response.
type CodeChange struct {
	FilePath string
	Lang     string
	Content  string // full new file content
	OldLines []string
	NewLines []string
}

// ParseCodeChanges scans an AI response for fenced code blocks that include a file path.
// Supported formats:
//
//	```lang path/to/file
//	<content>
//	```
//
// or
//
//	```path/to/file.ext
//	<content>
//	```
func ParseCodeChanges(response string) []CodeChange {
	// Regex: ```<optional-lang> <path-with-extension-or-slash>
	re := regexp.MustCompile("(?m)^```([a-zA-Z0-9_+-]*)\\s+([^\\n`]+)\\n([\\s\\S]*?)^```")
	matches := re.FindAllStringSubmatch(response, -1)

	var changes []CodeChange
	seen := map[string]bool{}

	for _, m := range matches {
		lang := strings.TrimSpace(m[1])
		path := strings.TrimSpace(m[2])
		content := m[3]

		// Skip if path looks like a random word (no slash, dot, or known extension)
		if !looksLikePath(path) {
			continue
		}
		// De-duplicate by file path (keep last occurrence)
		if seen[path] {
			// Remove the previous entry, we'll overwrite
			for i, c := range changes {
				if c.FilePath == path {
					changes = append(changes[:i], changes[i+1:]...)
					break
				}
			}
		}
		seen[path] = true

		newLines := strings.Split(strings.TrimRight(content, "\n"), "\n")
		change := CodeChange{
			FilePath: path,
			Lang:     lang,
			Content:  content,
			NewLines: newLines,
		}

		// Read existing file to build oldLines for diff context
		if data, err := os.ReadFile(path); err == nil {
			change.OldLines = strings.Split(strings.TrimRight(string(data), "\n"), "\n")
		}

		changes = append(changes, change)
	}

	return changes
}

func looksLikePath(s string) bool {
	if strings.Contains(s, "/") || strings.Contains(s, "\\") {
		return true
	}
	if idx := strings.LastIndex(s, "."); idx > 0 && idx < len(s)-1 {
		ext := s[idx+1:]
		known := []string{
			"go", "py", "js", "ts", "jsx", "tsx", "html", "css", "json",
			"yaml", "yml", "toml", "sh", "md", "sql", "rs", "java", "c",
			"cpp", "h", "rb", "php", "swift", "kt", "scala", "tf", "env",
		}
		for _, k := range known {
			if ext == k {
				return true
			}
		}
	}
	return false
}

// buildUnifiedDiff produces a simple unified diff between old and new lines.
// context is how many unchanged lines to show around each hunk (default 3).
func buildUnifiedDiff(old, new []string, context int) []DiffLine {
	// Myers-style LCS diff via simple DP
	type edit struct {
		op   rune // ' ' keep, '+' add, '-' del
		text string
	}
	edits := lcs(old, new)

	var result []DiffLine
	for _, e := range edits {
		switch e.op {
		case ' ':
			result = append(result, DiffLine{Op: ' ', Text: e.text})
		case '+':
			result = append(result, DiffLine{Op: '+', Text: e.text})
		case '-':
			result = append(result, DiffLine{Op: '-', Text: e.text})
		}
	}

	// Filter to show only changed lines ± context unchanged lines
	changed := map[int]bool{}
	for i, dl := range result {
		if dl.Op != ' ' {
			for j := max(0, i-context); j <= min(len(result)-1, i+context); j++ {
				changed[j] = true
			}
		}
	}

	// If no changes detected, mark everything as context
	if len(changed) == 0 {
		return result
	}

	var filtered []DiffLine
	prevIncluded := false
	for i, dl := range result {
		if changed[i] {
			if !prevIncluded && i > 0 {
				filtered = append(filtered, DiffLine{Op: '@', Text: fmt.Sprintf("@@ -%d +%d @@", i, i)})
			}
			filtered = append(filtered, dl)
			prevIncluded = true
		} else {
			prevIncluded = false
		}
	}
	return filtered
}

type edit struct {
	op   rune
	text string
}

// lcs computes the longest-common-subsequence diff between two string slices.
func lcs(old, new []string) []edit {
	m, n := len(old), len(new)
	dp := make([][]int, m+1)
	for i := range dp {
		dp[i] = make([]int, n+1)
	}
	for i := m - 1; i >= 0; i-- {
		for j := n - 1; j >= 0; j-- {
			if old[i] == new[j] {
				dp[i][j] = dp[i+1][j+1] + 1
			} else {
				if dp[i+1][j] > dp[i][j+1] {
					dp[i][j] = dp[i+1][j]
				} else {
					dp[i][j] = dp[i][j+1]
				}
			}
		}
	}

	var edits []edit
	i, j := 0, 0
	for i < m && j < n {
		if old[i] == new[j] {
			edits = append(edits, edit{' ', old[i]})
			i++
			j++
		} else if dp[i+1][j] >= dp[i][j+1] {
			edits = append(edits, edit{'-', old[i]})
			i++
		} else {
			edits = append(edits, edit{'+', new[j]})
			j++
		}
	}
	for ; i < m; i++ {
		edits = append(edits, edit{'-', old[i]})
	}
	for ; j < n; j++ {
		edits = append(edits, edit{'+', new[j]})
	}
	return edits
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// DiffLine is a single line in the rendered unified diff.
type DiffLine struct {
	Op   rune // ' ' context, '+' add, '-' del, '@' hunk header
	Text string
}

// DiffReviewView is the Bubble Tea sub-model for reviewing AI code changes.
type DiffReviewView struct {
	Changes  []CodeChange
	Current  int  // index into Changes
	Visible  bool
	Width    int
	Height   int
	scrollY  int
	diffLines []DiffLine // cached diff for current change
	Status   string      // "accepted" | "rejected" | ""
	Results  []DiffResult
}

// DiffResult records what happened to each change.
type DiffResult struct {
	FilePath string
	Action   string // "accepted" | "rejected" | "edited"
}

func NewDiffReviewView() *DiffReviewView {
	return &DiffReviewView{}
}

// Load sets the changes to review and resets state.
func (d *DiffReviewView) Load(changes []CodeChange) {
	d.Changes = changes
	d.Current = 0
	d.Results = nil
	d.scrollY = 0
	d.Visible = len(changes) > 0
	d.Status = ""
	d.rebuildDiff()
}

func (d *DiffReviewView) rebuildDiff() {
	if d.Current >= len(d.Changes) {
		d.diffLines = nil
		return
	}
	ch := d.Changes[d.Current]
	d.diffLines = buildUnifiedDiff(ch.OldLines, ch.NewLines, 3)
	d.scrollY = 0
	d.Status = ""
}

// CurrentChange returns the active change or nil.
func (d *DiffReviewView) CurrentChange() *CodeChange {
	if d.Current < len(d.Changes) {
		return &d.Changes[d.Current]
	}
	return nil
}

// Done returns true when all changes have been reviewed.
func (d *DiffReviewView) Done() bool {
	return d.Current >= len(d.Changes)
}

// Accept writes the current change to disk and advances.
func (d *DiffReviewView) Accept() error {
	ch := d.CurrentChange()
	if ch == nil {
		return nil
	}
	dir := filepath.Dir(ch.FilePath)
	if dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return err
		}
	}
	if err := os.WriteFile(ch.FilePath, []byte(ch.Content), 0644); err != nil {
		return err
	}
	d.Results = append(d.Results, DiffResult{ch.FilePath, "accepted"})
	d.advance()
	return nil
}

// Reject skips the current change without writing.
func (d *DiffReviewView) Reject() {
	ch := d.CurrentChange()
	if ch == nil {
		return
	}
	d.Results = append(d.Results, DiffResult{ch.FilePath, "rejected"})
	d.advance()
}

// EditInEditor opens the current change in $EDITOR, then reads the result.
// Returns an error if the editor launch fails.
func (d *DiffReviewView) EditInEditor() error {
	ch := d.CurrentChange()
	if ch == nil {
		return nil
	}

	// Write to a temp file
	tmp, err := os.CreateTemp("", "archie-diff-*."+langExt(ch.Lang, ch.FilePath))
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	_, _ = tmp.WriteString(ch.Content)
	tmp.Close()

	editor := os.Getenv("EDITOR")
	if editor == "" {
		editor = "vi"
	}

	cmd := exec.Command(editor, tmpPath)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		os.Remove(tmpPath)
		return err
	}

	// Read back the edited content
	edited, err := os.ReadFile(tmpPath)
	os.Remove(tmpPath)
	if err != nil {
		return err
	}

	// Update the change with edited content
	d.Changes[d.Current].Content = string(edited)
	d.Changes[d.Current].NewLines = strings.Split(strings.TrimRight(string(edited), "\n"), "\n")

	// Write to the actual file
	dir := filepath.Dir(ch.FilePath)
	if dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return err
		}
	}
	if err := os.WriteFile(ch.FilePath, edited, 0644); err != nil {
		return err
	}

	d.Results = append(d.Results, DiffResult{ch.FilePath, "edited"})
	d.advance()
	return nil
}

func (d *DiffReviewView) advance() {
	d.Current++
	if !d.Done() {
		d.rebuildDiff()
	} else {
		d.Visible = false
	}
}

// ScrollUp scrolls the diff view up.
func (d *DiffReviewView) ScrollUp() {
	if d.scrollY > 0 {
		d.scrollY--
	}
}

// ScrollDown scrolls the diff view down.
func (d *DiffReviewView) ScrollDown() {
	maxScroll := len(d.diffLines) - (d.Height - 10)
	if maxScroll < 0 {
		maxScroll = 0
	}
	if d.scrollY < maxScroll {
		d.scrollY++
	}
}

// Render draws the diff review panel.
func (d *DiffReviewView) Render() string {
	if !d.Visible || d.Done() {
		return ""
	}

	ch := d.CurrentChange()
	if ch == nil {
		return ""
	}

	w := d.Width
	if w == 0 {
		w = 80
	}

	var sb strings.Builder

	// ── Header bar ──
	idx := fmt.Sprintf("[%d/%d]", d.Current+1, len(d.Changes))
	title := fmt.Sprintf(" DIFF REVIEW %s — %s ", idx, ch.FilePath)
	pad := w - len(title)
	if pad < 0 {
		pad = 0
	}
	headerLine := diffBorderStyle.Render("╔" + strings.Repeat("═", w-2) + "╗")
	titleLine := diffBorderStyle.Render("║") +
		diffHeaderStyle.Render(title) +
		strings.Repeat(" ", pad) +
		diffBorderStyle.Render("║")
	sb.WriteString(headerLine + "\n")
	sb.WriteString(titleLine + "\n")
	sb.WriteString(diffBorderStyle.Render("╠"+strings.Repeat("═", w-2)+"╣") + "\n")

	// ── Diff lines ──
	viewH := d.Height - 10
	if viewH < 5 {
		viewH = 5
	}

	lines := d.diffLines
	start := d.scrollY
	end := start + viewH
	if end > len(lines) {
		end = len(lines)
	}
	if start > len(lines) {
		start = len(lines)
	}

	if len(lines) == 0 {
		sb.WriteString(diffCtxStyle.Render("  (new file — no previous content)") + "\n")
	}

	for _, dl := range lines[start:end] {
		var rendered string
		switch dl.Op {
		case '+':
			rendered = diffAddStyle.Render(fmt.Sprintf("  + %s", dl.Text))
		case '-':
			rendered = diffDelStyle.Render(fmt.Sprintf("  - %s", dl.Text))
		case '@':
			rendered = diffIndexStyle.Render(fmt.Sprintf("  %s", dl.Text))
		default:
			rendered = diffCtxStyle.Render(fmt.Sprintf("    %s", dl.Text))
		}
		sb.WriteString(rendered + "\n")
	}

	// Pad to fill viewH
	shown := end - start
	for i := shown; i < viewH; i++ {
		sb.WriteString("\n")
	}

	// Scroll indicator
	scrollInfo := ""
	if len(lines) > viewH {
		scrollInfo = diffCtxStyle.Render(fmt.Sprintf("  [↑/↓ scroll — line %d/%d]", d.scrollY+1, len(lines)))
	}
	sb.WriteString(scrollInfo + "\n")

	// ── Separator ──
	sb.WriteString(diffBorderStyle.Render("╠"+strings.Repeat("═", w-2)+"╣") + "\n")

	// ── Keybindings footer ──
	keybinds := fmt.Sprintf("  %s accept   %s reject   %s edit in $EDITOR   %s/%s prev/next   %s quit review",
		diffAcceptStyle.Render("[a]"),
		diffRejectStyle.Render("[r]"),
		diffEditStyle.Render("[e]"),
		diffIndexStyle.Render("[p]"),
		diffIndexStyle.Render("[n]"),
		diffCtxStyle.Render("[q]"),
	)
	sb.WriteString(keybinds + "\n")
	sb.WriteString(diffBorderStyle.Render("╚"+strings.Repeat("═", w-2)+"╝") + "\n")

	return sb.String()
}

// SummaryMessage returns a human-readable summary of all diff results.
func (d *DiffReviewView) SummaryMessage() string {
	if len(d.Results) == 0 {
		return "No changes were reviewed."
	}
	var parts []string
	accepted, rejected, edited := 0, 0, 0
	for _, r := range d.Results {
		switch r.Action {
		case "accepted":
			accepted++
		case "rejected":
			rejected++
		case "edited":
			edited++
		}
	}
	if accepted > 0 {
		parts = append(parts, fmt.Sprintf("%d accepted", accepted))
	}
	if edited > 0 {
		parts = append(parts, fmt.Sprintf("%d edited", edited))
	}
	if rejected > 0 {
		parts = append(parts, fmt.Sprintf("%d rejected", rejected))
	}
	return "Diff review complete: " + strings.Join(parts, ", ") + "."
}

func langExt(lang, path string) string {
	if lang != "" {
		switch lang {
		case "python":
			return "py"
		case "javascript":
			return "js"
		case "typescript":
			return "ts"
		case "golang", "go":
			return "go"
		case "bash", "sh":
			return "sh"
		default:
			return lang
		}
	}
	if idx := strings.LastIndex(path, "."); idx >= 0 {
		return path[idx+1:]
	}
	return "txt"
}
