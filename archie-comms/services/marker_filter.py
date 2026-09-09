"""Keep ``{{...}}`` markers out of the streamed cockpit view (#6654).

A.R.C.H.I.E.'s streamed reply carries interactive markers
(``{{DELEGATE}}`` / ``{{APPROVALS}}`` / ``{{APPROVE}}`` / ``{{DENY}}`` /
``{{DEEPEN}}`` / ``{{CONSULT:…}}`` / ``{{ACTION:…}}``) that the harvest logic in
``conversation_service`` reads from the RAW accumulated text. When the reply is
streamed token-by-token, a marker can arrive split across tokens, so this filter
sits between the token source and the browser: it buffers from a ``{{`` until it
sees the closing ``}}`` (then DROPS the whole marker) or until the buffer exceeds
``cap`` chars with no close (then it was not a marker — release it). Plain text
with no ``{{`` streams straight through. The harvest still fires because it works
off the separate raw accumulation, which keeps the markers.
"""

DEFAULT_CAP = 64


class MarkerFilter:
    def __init__(self, cap: int = DEFAULT_CAP):
        self._buf = ""  # text held back because it might be an open marker
        self._cap = cap

    def feed(self, text: str) -> str:
        """Return the portion of ``text`` (plus anything previously held) that is
        safe to show now — markers dropped, an in-progress ``{{…`` held back."""
        data = self._buf + (text or "")
        self._buf = ""
        out = []
        i, n = 0, len(data)
        while i < n:
            open_idx = data.find("{{", i)
            if open_idx == -1:
                chunk = data[i:]
                # A lone trailing '{' might become '{{' on the next token — hold it.
                if chunk.endswith("{"):
                    self._buf = "{"
                    chunk = chunk[:-1]
                out.append(chunk)
                break
            out.append(data[i:open_idx])
            close_idx = data.find("}}", open_idx)
            if close_idx == -1:
                held = data[open_idx:]
                if len(held) > self._cap:
                    out.append(held)  # too long to be a marker — release it
                else:
                    self._buf = held  # open marker, still waiting for '}}'
                break
            i = close_idx + 2  # complete marker → drop it
        return "".join(out)

    def flush(self) -> str:
        """End of stream: release whatever is held. An unterminated ``{{…`` was a
        marker the model never closed — drop it rather than flash it."""
        tail = self._buf
        self._buf = ""
        return "" if tail.startswith("{{") else tail
