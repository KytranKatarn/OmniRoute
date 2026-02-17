"""
Conversation Triage System
Phase 42: Knowledge extraction pipeline for Claude Code conversations

Extracts valuable knowledge from raw conversation transcripts:
- Mistakes and error patterns (→ mistake_learned)
- Code snippets and patterns (→ code_snippet)
- Architecture decisions (→ improvement)
- Insights and learnings (→ vault_note)
"""

from .classifier import ConversationClassifier
from .triage_pipeline import TriagePipeline

__all__ = ["ConversationClassifier", "TriagePipeline"]
