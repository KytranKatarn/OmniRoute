"""
Triage Pipeline
Main orchestrator for the conversation triage system.

Coordinates:
1. Classification (topic, phase, urgency)
2. Extraction (errors, code, insights)
3. Knowledge Base insertion
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from .classifier import ConversationClassifier, Classification
from .extractors.error_extractor import ErrorExtractor, ExtractedError
from .extractors.code_extractor import CodeExtractor, ExtractedCode
from .extractors.insight_extractor import InsightExtractor, ExtractedInsight

logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    """Complete result of triaging a conversation."""
    classification: Classification
    errors: List[ExtractedError]
    code_snippets: List[ExtractedCode]
    insights: List[ExtractedInsight]
    processing_time_ms: int
    summary: str


class TriagePipeline:
    """Orchestrates the full triage process."""

    def __init__(self, db_connection=None):
        """Initialize the pipeline with optional database connection."""
        self.db = db_connection
        self.classifier = ConversationClassifier()
        self.error_extractor = ErrorExtractor()
        self.code_extractor = CodeExtractor()
        self.insight_extractor = InsightExtractor()

    def process(self, content: str, conversation_id: Optional[int] = None) -> TriageResult:
        """
        Process a conversation through the full triage pipeline.

        Args:
            content: Raw conversation text
            conversation_id: Optional ID from knowledge_base for tracking

        Returns:
            TriageResult with all extractions
        """
        start_time = datetime.now()

        # Stage 1: Classification
        classification = self.classifier.classify(content)
        logger.info(f"Classified as {classification.phase}/{classification.primary_topic} "
                   f"(urgency: {classification.urgency_score:.2f})")

        # Stage 2: Extraction (parallel in concept, sequential here)
        errors = self.error_extractor.extract(content)
        code_snippets = self.code_extractor.extract(content)
        insights = self.insight_extractor.extract(content)

        logger.info(f"Extracted: {len(errors)} errors, {len(code_snippets)} snippets, "
                   f"{len(insights)} insights")

        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # Generate summary
        summary = self._generate_summary(classification, errors, code_snippets, insights)

        result = TriageResult(
            classification=classification,
            errors=errors,
            code_snippets=code_snippets,
            insights=insights,
            processing_time_ms=processing_time,
            summary=summary
        )

        # Stage 3: Database insertion (if connected)
        if self.db and conversation_id:
            self._save_to_database(result, conversation_id)

        return result

    def _generate_summary(
        self,
        classification: Classification,
        errors: List[ExtractedError],
        code_snippets: List[ExtractedCode],
        insights: List[ExtractedInsight]
    ) -> str:
        """Generate a human-readable summary of the triage."""
        parts = [
            f"**Topic:** {classification.primary_topic}",
            f"**Phase:** {classification.phase}",
            f"**Urgency:** {classification.urgency_score:.0%}",
            "",
            "**Extractions:**"
        ]

        if errors:
            parts.append(f"- {len(errors)} error(s) with solutions")
            for e in errors[:3]:
                parts.append(f"  - {e.title}")

        if code_snippets:
            parts.append(f"- {len(code_snippets)} code snippet(s)")
            for c in code_snippets[:3]:
                parts.append(f"  - {c.title} ({c.language})")

        if insights:
            parts.append(f"- {len(insights)} insight(s)")
            for i in insights[:3]:
                parts.append(f"  - {i.title}")

        if not errors and not code_snippets and not insights:
            parts.append("- No significant extractions")

        return '\n'.join(parts)

    def _save_to_database(self, result: TriageResult, conversation_id: int) -> None:
        """Save triage results to database."""
        try:
            cursor = self.db.cursor()

            # Insert into triage queue
            cursor.execute("""
                INSERT INTO conversation_triage_queue
                (conversation_id, status, priority, primary_topic, conversation_phase,
                 urgency_score, classification, extractions, processed_at, processing_duration_ms)
                VALUES (%s, 'completed', %s, %s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id
            """, (
                conversation_id,
                self._calculate_priority(result),
                result.classification.primary_topic,
                result.classification.phase,
                result.classification.urgency_score,
                self._classification_to_json(result.classification),
                self._extractions_to_json(result),
                result.processing_time_ms
            ))
            triage_id = cursor.fetchone()[0]

            # Insert individual extractions
            self._save_extractions(cursor, triage_id, result)

            self.db.commit()
            logger.info(f"Saved triage {triage_id} for conversation {conversation_id}")

        except Exception as e:
            logger.error(f"Failed to save triage: {e}")
            self.db.rollback()
            raise

    def _calculate_priority(self, result: TriageResult) -> int:
        """Calculate priority 1-10 based on content."""
        base = int(result.classification.urgency_score * 5) + 3  # 3-8

        # Boost for errors
        if result.errors:
            critical = any(e.severity == 'critical' for e in result.errors)
            high = any(e.severity == 'high' for e in result.errors)
            if critical:
                base = min(base + 3, 10)
            elif high:
                base = min(base + 1, 9)

        return base

    def _classification_to_json(self, classification: Classification) -> str:
        """Convert classification to JSON string."""
        import json
        return json.dumps({
            'primary_topic': classification.primary_topic,
            'phase': classification.phase,
            'urgency_score': classification.urgency_score,
            'tags': classification.tags,
            'confidence': classification.confidence
        })

    def _extractions_to_json(self, result: TriageResult) -> str:
        """Convert extractions to JSON string."""
        import json
        return json.dumps({
            'error_count': len(result.errors),
            'snippet_count': len(result.code_snippets),
            'insight_count': len(result.insights)
        })

    def _save_extractions(self, cursor, triage_id: int, result: TriageResult) -> None:
        """Save individual extractions to triage_extractions table."""
        import json

        # Save errors
        for error in result.errors:
            cursor.execute("""
                INSERT INTO triage_extractions
                (triage_id, extraction_type, title, content, severity, confidence_score, raw_extraction)
                VALUES (%s, 'error', %s, %s, %s, %s, %s)
            """, (
                triage_id,
                error.title,
                f"**Error:** {error.error_message}\n\n**Cause:** {error.cause}\n\n**Solution:** {error.solution}",
                error.severity,
                error.confidence,
                json.dumps(asdict(error))
            ))

        # Save code snippets
        for snippet in result.code_snippets:
            cursor.execute("""
                INSERT INTO triage_extractions
                (triage_id, extraction_type, title, content, language, confidence_score, raw_extraction)
                VALUES (%s, 'code_snippet', %s, %s, %s, %s, %s)
            """, (
                triage_id,
                snippet.title,
                f"**Purpose:** {snippet.purpose}\n\n```{snippet.language}\n{snippet.code}\n```",
                snippet.language,
                snippet.confidence,
                json.dumps(asdict(snippet))
            ))

        # Save insights
        for insight in result.insights:
            cursor.execute("""
                INSERT INTO triage_extractions
                (triage_id, extraction_type, title, content, confidence_score, raw_extraction)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                triage_id,
                'insight' if insight.insight_type == 'learning' else insight.insight_type,
                insight.title,
                insight.content,
                insight.confidence,
                json.dumps(asdict(insight))
            ))


def triage_conversation(content: str, db_connection=None, conversation_id: int = None) -> Dict[str, Any]:
    """
    Convenience function to triage a conversation.

    Args:
        content: Raw conversation text
        db_connection: Optional psycopg2 connection
        conversation_id: Optional knowledge_base ID

    Returns:
        Dictionary with triage results
    """
    pipeline = TriagePipeline(db_connection)
    result = pipeline.process(content, conversation_id)

    return {
        'classification': {
            'topic': result.classification.primary_topic,
            'phase': result.classification.phase,
            'urgency': result.classification.urgency_score,
            'tags': result.classification.tags
        },
        'extractions': {
            'errors': [asdict(e) for e in result.errors],
            'code_snippets': [asdict(c) for c in result.code_snippets],
            'insights': [asdict(i) for i in result.insights]
        },
        'summary': result.summary,
        'processing_time_ms': result.processing_time_ms
    }
