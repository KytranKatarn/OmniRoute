"""
Conversation Summarizer (Phase 6)

Uses Claude API to summarize development conversations and extract:
- Key insights
- Decisions made
- Code patterns learned
- Action items
- Knowledge to preserve

Author: A.R.C.H.I.E. Platform
Date: 2026-01-10
Phase: 6 - Full Conversation Memory System
"""

import sys
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger('archie_platform')


class ConversationSummarizer:
    """
    Summarizes Claude Code development conversations using Claude API.

    Features:
    - Extract key insights and learnings
    - Identify decisions made
    - Detect code patterns
    - Calculate productivity and learning scores
    """

    def __init__(self):
        """Initialize summarizer"""
        try:
            from archie_bridge import archie_bridge
            self.archie_bridge = archie_bridge
            self.available = True
        except ImportError:
            logger.warning("[Conversation Summarizer] archie_bridge not available")
            self.available = False

    def summarize_conversation(
        self,
        transcript: str,
        session_metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Summarize a conversation transcript using Claude API.

        Args:
            transcript: Full conversation text
            session_metadata: Optional metadata about the session

        Returns:
            Dict with summary, insights, decisions, etc.
        """
        if not self.available:
            logger.error("[Conversation Summarizer] archie_bridge not available")
            return self._fallback_summary(transcript)

        if not transcript or len(transcript) < 100:
            logger.warning("[Conversation Summarizer] Transcript too short to summarize")
            return self._fallback_summary(transcript)

        try:
            logger.info(f"[Conversation Summarizer] Summarizing conversation ({len(transcript)} chars)")

            # Build summarization prompt
            prompt = self._build_summarization_prompt(transcript, session_metadata)

            # Call Claude API via archie_bridge
            result = self.archie_bridge(
                prompt=prompt,
                context="",
                user_id=2,  # Admin
                force_model='claude-sonnet-4',  # Use powerful model for summarization
                enable_memory=False  # Don't store this meta-conversation
            )

            if not result.get('success'):
                logger.error(f"[Conversation Summarizer] Claude API call failed: {result.get('error')}")
                return self._fallback_summary(transcript)

            response = result.get('response', '')

            # Parse structured response
            summary_data = self._parse_summary_response(response)

            # Calculate scores
            summary_data['productivity_score'] = self._calculate_productivity_score(summary_data)
            summary_data['learning_value'] = self._calculate_learning_value(summary_data)
            summary_data['code_quality'] = self._calculate_code_quality(summary_data)

            logger.info(f"[Conversation Summarizer] Summary complete - {len(summary_data.get('key_insights', []))} insights extracted")

            return summary_data

        except Exception as e:
            logger.error(f"[Conversation Summarizer] Error summarizing conversation: {e}")
            return self._fallback_summary(transcript)

    def _build_summarization_prompt(
        self,
        transcript: str,
        session_metadata: Optional[Dict]
    ) -> str:
        """Build prompt for Claude to summarize conversation"""

        metadata_context = ""
        if session_metadata:
            metadata_context = f"""
**Session Context:**
- Session: {session_metadata.get('session_name', 'unknown')}
- Git Branch: {session_metadata.get('git_branch', 'unknown')}
- Phase: {session_metadata.get('phase', 'unknown')}
- Topic: {session_metadata.get('primary_topic', 'general')}
"""

        prompt = f"""You are analyzing a Claude Code development session to extract key learnings and insights.

{metadata_context}

**Your Task:**
Analyze the following conversation transcript and extract:

1. **Summary** (2-3 sentences): What was accomplished in this session?

2. **Key Insights** (3-5 bullet points): Important learnings, discoveries, or realizations

3. **Decisions Made** (list): What decisions were made about architecture, implementation, or approach?

4. **Code Patterns Learned** (list): New code patterns, techniques, or best practices discovered

5. **Action Items** (list): What needs to be done next or follow-up tasks

6. **Tags** (5-10 keywords): Topics covered in the conversation

**Respond in JSON format ONLY:**
```json
{{
  "summary": "...",
  "key_insights": [
    {{"insight": "...", "importance": 0.8}},
    ...
  ],
  "decisions_made": [
    {{"decision": "...", "rationale": "...", "impact": "high|medium|low"}}
  ],
  "code_patterns_learned": [
    {{"pattern": "...", "description": "...", "usefulness": 0.7}}
  ],
  "action_items": ["...", "..."],
  "tags": ["database", "api", "testing", ...]
}}
```

**Conversation Transcript:**
```
{transcript[:8000]}  # Limit to 8000 chars to avoid token limits
{f'... (truncated, full length: {len(transcript)} chars)' if len(transcript) > 8000 else ''}
```

**Respond with ONLY the JSON, no other text.**
"""

        return prompt

    def _parse_summary_response(self, response: str) -> Dict[str, Any]:
        """Parse Claude's structured JSON response"""
        try:
            # Extract JSON from response (might be wrapped in ```json```)
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)

                # Validate structure
                return {
                    'summary': data.get('summary', ''),
                    'key_insights': data.get('key_insights', []),
                    'decisions_made': data.get('decisions_made', []),
                    'code_patterns_learned': data.get('code_patterns_learned', []),
                    'action_items': data.get('action_items', []),
                    'tags': data.get('tags', []),
                    'raw_response': response
                }
            else:
                logger.warning("[Conversation Summarizer] No JSON found in response")
                return self._extract_fallback_insights(response)

        except json.JSONDecodeError as e:
            logger.error(f"[Conversation Summarizer] JSON parse error: {e}")
            return self._extract_fallback_insights(response)
        except Exception as e:
            logger.error(f"[Conversation Summarizer] Parse error: {e}")
            return self._extract_fallback_insights(response)

    def _extract_fallback_insights(self, response: str) -> Dict[str, Any]:
        """Extract insights from non-JSON response"""
        return {
            'summary': response[:500] if response else 'No summary available',
            'key_insights': [],
            'decisions_made': [],
            'code_patterns_learned': [],
            'action_items': [],
            'tags': [],
            'raw_response': response,
            'fallback': True
        }

    def _calculate_productivity_score(self, summary_data: Dict) -> float:
        """
        Calculate productivity score (0.0-1.0) based on what was accomplished.

        Factors:
        - Number of decisions made
        - Action items completed vs created
        - Code patterns learned
        """
        score = 0.5  # Base score

        # Decisions add to productivity
        decisions = len(summary_data.get('decisions_made', []))
        if decisions > 0:
            score += min(decisions * 0.1, 0.3)  # Max +0.3

        # Code patterns indicate productive coding
        patterns = len(summary_data.get('code_patterns_learned', []))
        if patterns > 0:
            score += min(patterns * 0.05, 0.15)  # Max +0.15

        # Insights suggest deep work
        insights = len(summary_data.get('key_insights', []))
        if insights > 0:
            score += min(insights * 0.02, 0.1)  # Max +0.1

        return min(score, 1.0)

    def _calculate_learning_value(self, summary_data: Dict) -> float:
        """
        Calculate learning value (0.0-1.0) based on knowledge gained.

        Factors:
        - Key insights extracted
        - Importance of insights
        - Code patterns learned
        """
        score = 0.3  # Base score

        # Insights are primary learning indicator
        insights = summary_data.get('key_insights', [])
        if insights:
            # Weight by importance
            avg_importance = sum(i.get('importance', 0.5) for i in insights) / len(insights)
            score += avg_importance * 0.4  # Max +0.4

        # Code patterns add learning value
        patterns = summary_data.get('code_patterns_learned', [])
        if patterns:
            avg_usefulness = sum(p.get('usefulness', 0.5) for p in patterns) / len(patterns)
            score += avg_usefulness * 0.3  # Max +0.3

        return min(score, 1.0)

    def _calculate_code_quality(self, summary_data: Dict) -> float:
        """
        Calculate code quality score (0.0-1.0) based on decisions and patterns.

        Factors:
        - Quality of decisions made
        - Patterns learned
        - Presence of "best practice" keywords
        """
        score = 0.6  # Base score (assume decent quality)

        # High-impact decisions suggest good quality
        decisions = summary_data.get('decisions_made', [])
        high_impact = sum(1 for d in decisions if d.get('impact') == 'high')
        if high_impact > 0:
            score += min(high_impact * 0.1, 0.2)  # Max +0.2

        # Code patterns suggest quality
        patterns = summary_data.get('code_patterns_learned', [])
        if patterns:
            score += min(len(patterns) * 0.05, 0.2)  # Max +0.2

        return min(score, 1.0)

    def _fallback_summary(self, transcript: str) -> Dict[str, Any]:
        """Create basic summary without Claude API"""
        words = transcript.split()
        word_count = len(words)

        return {
            'summary': f"Development session with {word_count} words of conversation",
            'key_insights': [],
            'decisions_made': [],
            'code_patterns_learned': [],
            'action_items': [],
            'tags': [],
            'productivity_score': 0.5,
            'learning_value': 0.5,
            'code_quality': 0.6,
            'fallback': True,
            'error': 'Claude API not available'
        }


# Singleton instance
_summarizer_instance = None

def get_conversation_summarizer():
    """Get singleton conversation summarizer instance"""
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = ConversationSummarizer()
    return _summarizer_instance
