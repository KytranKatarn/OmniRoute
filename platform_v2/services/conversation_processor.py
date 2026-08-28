"""
Conversation Processor (Phase 6)

Processes Claude Code development sessions:
1. Extracts conversation data from Claude sessions
2. Summarizes using Claude API
3. Creates knowledge_base entries (type=conversation_memory)
4. Stores in conversation_sessions table

Author: A.R.C.H.I.E. Platform
Date: 2026-01-10
Phase: 6 - Full Conversation Memory System
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import glob
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("archie_platform")

# Import conversation summarizer
try:
    from services.conversation_summarizer import get_conversation_summarizer

    SUMMARIZER_AVAILABLE = True
except ImportError:
    SUMMARIZER_AVAILABLE = False
    logger.warning("[Conversation Processor] Conversation summarizer not available")


class ConversationProcessor:
    """
    Processes Claude Code conversation sessions into knowledge entries.

    Features:
    - Extracts metadata from hook snapshots
    - Summarizes conversations using Claude API
    - Creates conversation_memory entries in knowledge_base
    - Stores session records in conversation_sessions
    """

    def __init__(self, db_connection=None):
        """Initialize with optional database connection"""
        self.db = db_connection
        self.logs_dir = os.getenv("CONVERSATION_LOGS_DIR", "/mnt/archie_brain/conversation_logs")

    def process_snapshot(self, snapshot_file: str) -> Dict[str, Any]:
        """
        Process a single snapshot from PreCompact hook.

        ENHANCED: Now handles full conversation capture with messages array.

        Args:
            snapshot_file: Path to snapshot JSON file

        Returns:
            Dict with processing result
        """
        try:
            logger.info(f"[Conversation Processor] Processing snapshot: {snapshot_file}")

            # Read snapshot
            with open(snapshot_file, "r") as f:
                snapshot = json.load(f)

            # Extract metadata
            session_name = snapshot.get("session_name", "unknown")
            session_id_str = snapshot.get("session_id", "unknown")
            git_branch = snapshot.get("git_branch", "unknown")
            git_commit = snapshot.get("git_commit", "unknown")
            working_directory = snapshot.get("working_directory", "")
            timestamp = snapshot.get("timestamp", datetime.now().isoformat())
            message_count = snapshot.get("message_count", 0)

            # Parse timestamp
            try:
                compact_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                compact_time = datetime.now()

            # Check if already processed
            if self.db:
                existing = self._check_existing_session(session_name=session_name, compact_time=compact_time)
                if existing:
                    logger.info(f"[Conversation Processor] Session already processed: {existing['id']}")
                    return {
                        "success": True,
                        "session_id": existing["id"],
                        "already_processed": True,
                    }

            # Extract full conversation transcript from messages
            messages = snapshot.get("messages", [])
            full_transcript = ""
            transcript_file = snapshot.get("transcript_file")

            if messages:
                logger.info(f"[Conversation Processor] Found {len(messages)} messages in snapshot")

                # Build transcript from messages
                transcript_parts = []
                for i, msg in enumerate(messages, 1):
                    content = msg.get("content", "")
                    timestamp_msg = msg.get("timestamp", "Unknown")
                    transcript_parts.append(f"=== Message {i} ({timestamp_msg}) ===\n{content}\n")

                full_transcript = "\n".join(transcript_parts)

            elif transcript_file and os.path.exists(transcript_file):
                # Read transcript from separate file
                logger.info(f"[Conversation Processor] Reading transcript from {transcript_file}")
                with open(transcript_file, "r", encoding="utf-8") as f:
                    full_transcript = f.read()

            else:
                logger.warning("[Conversation Processor] No conversation data found in snapshot")

            # Extract git timeline from snapshot
            git_timeline = snapshot.get("git_timeline", {})

            # Extract insights from messages using enhanced extraction
            insights = {}
            if messages:
                insights = self.extract_insights(messages, git_timeline)
                logger.info("[Conversation Processor] Extracted insights:")
                logger.info(f"   Code changes: {len(insights.get('code_changes', []))}")
                logger.info(f"   Mistakes found: {len(insights.get('mistakes_found', []))}")
                logger.info(f"   Categories: {insights.get('archie_categories', [])}")

            # Create session entry WITH full transcript
            session_id = self._create_session_entry(
                session_name=session_name,
                git_branch=git_branch,
                git_commit=git_commit,
                working_directory=working_directory,
                compact_time=compact_time,
                snapshot_metadata=snapshot,
                full_transcript=full_transcript if full_transcript else None,
            )

            if session_id:
                logger.info(f"[Conversation Processor] Created session #{session_id}")
                logger.info(f"   Session ID (Claude): {session_id_str}")
                logger.info(f"   Messages: {message_count}")
                logger.info(f"   Transcript length: {len(full_transcript)} chars")

                # Use Archie_Brain categories for topic if available
                archie_categories = insights.get("archie_categories", [])
                primary_category = archie_categories[0] if archie_categories else self._determine_topic(session_name)

                # Generate enhanced tags including Archie_Brain categories
                tags = self._generate_tags(session_name, git_branch)
                tags.extend(archie_categories)
                tags = list(set(tags))  # Dedupe

                # Create immediate knowledge entry for the raw conversation
                knowledge_entry_id = None
                if full_transcript and self.db:
                    knowledge_entry_id = self._create_immediate_knowledge_entry(
                        session_id=session_id,
                        session_name=session_name,
                        git_branch=git_branch,
                        phase=self._determine_phase(session_name, git_branch),
                        topic=primary_category,
                        summary=snapshot.get("conversation_summary", full_transcript[:500] + "..."),
                        tags=tags,
                    )

                # Create mistake_learned entries if errors were detected
                mistake_entries = []
                if insights.get("mistakes_found") and insights.get("solutions_learned") and self.db:
                    for i, mistake in enumerate(insights["mistakes_found"][:3]):  # Max 3 per session
                        solution = (
                            insights["solutions_learned"][i]
                            if i < len(insights["solutions_learned"])
                            else {"pattern": "See conversation"}
                        )
                        mistake_id = self.create_mistake_learned_entry(
                            error_description=f"Error pattern: {mistake.get('pattern', 'unknown')}",
                            solution=f"Solution pattern: {solution.get('pattern', 'unknown')}",
                            context={
                                "session_id": session_id,
                                "session_name": session_name,
                                "git_branch": git_branch,
                            },
                        )
                        if mistake_id:
                            mistake_entries.append(mistake_id)

                return {
                    "success": True,
                    "session_id": session_id,
                    "session_id_claude": session_id_str,
                    "session_name": session_name,
                    "git_branch": git_branch,
                    "message_count": message_count,
                    "transcript_length": len(full_transcript),
                    "knowledge_entry_id": knowledge_entry_id,
                    "insights": insights,
                    "archie_categories": archie_categories,
                    "git_timeline": git_timeline,
                    "mistake_entries_created": len(mistake_entries),
                }
            else:
                return {"success": False, "error": "Failed to create session entry"}

        except Exception as e:
            logger.error(f"[Conversation Processor] Error processing snapshot: {e}")
            import traceback

            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def _check_existing_session(self, session_name: str, compact_time: datetime) -> Optional[Dict]:
        """Check if session already exists"""
        try:
            cur = self.db.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT id FROM conversation_sessions
                WHERE session_name = %s
                  AND compact_triggered_at = %s
                LIMIT 1
            """,
                (session_name, compact_time),
            )

            result = cur.fetchone()
            cur.close()

            return dict(result) if result else None

        except Exception as e:
            logger.error(f"[Conversation Processor] Error checking existing session: {e}")
            return None

    def _create_session_entry(
        self,
        session_name: str,
        git_branch: str,
        git_commit: str,
        working_directory: str,
        compact_time: datetime,
        snapshot_metadata: Dict,
        full_transcript: Optional[str] = None,
    ) -> Optional[int]:
        """Create conversation_sessions entry with optional full transcript"""
        try:
            if not self.db:
                logger.warning("[Conversation Processor] No database connection")
                return None

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            # Determine phase from session name or git branch
            phase = self._determine_phase(session_name, git_branch)

            # Determine primary topic (heuristic based on session name)
            primary_topic = self._determine_topic(session_name)

            cur.execute(
                """
                INSERT INTO conversation_sessions (
                    session_name,
                    git_branch,
                    git_commit,
                    working_directory,
                    started_at,
                    compact_triggered_at,
                    phase,
                    primary_topic,
                    processing_status,
                    metadata,
                    full_transcript
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, 'raw', %s, %s
                ) RETURNING id
            """,
                (
                    session_name,
                    git_branch,
                    git_commit,
                    working_directory,
                    compact_time,  # Use compact time as started_at for now
                    compact_time,
                    phase,
                    primary_topic,
                    json.dumps(snapshot_metadata),
                    full_transcript,
                ),
            )

            result = cur.fetchone()
            session_id = result["id"]

            self.db.commit()
            cur.close()

            logger.info(f"[Conversation Processor] Created session #{session_id} for {session_name}")
            if full_transcript:
                logger.info(f"   With full transcript ({len(full_transcript)} chars)")
            return session_id

        except Exception as e:
            logger.error(f"[Conversation Processor] Error creating session entry: {e}")
            if self.db:
                self.db.rollback()
            return None

    def _generate_tags(self, session_name: str, git_branch: str) -> List[str]:
        """Generate tags for conversation based on context"""
        tags = []

        # Add phase tag
        phase = self._determine_phase(session_name, git_branch)
        if phase != "General":
            tags.append(phase.lower().replace(" ", "-"))

        # Add topic tags
        topic = self._determine_topic(session_name)
        tags.append(topic)

        # Add git branch as tag
        if git_branch and git_branch != "unknown":
            tags.append(f"branch:{git_branch}")

        # Add generic tags
        tags.extend(["conversation", "session", "memory"])

        return list(set(tags))  # Remove duplicates

    def extract_insights(self, messages: List[Dict], git_timeline: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Extract structured insights from conversation messages.

        Phase 6 Enhancement: Full insight extraction with Archie_Brain categories.

        Args:
            messages: List of conversation messages
            git_timeline: Git time-dimension data from snapshot

        Returns:
            Dict with extracted insights
        """
        insights = {
            "code_changes": [],  # Files modified
            "decisions_made": [],  # Architectural decisions
            "mistakes_found": [],  # Errors encountered
            "solutions_learned": [],  # How errors were fixed
            "key_concepts": [],  # Important topics
            "todos_created": [],  # Tasks identified
            "git_commits": [],  # Related commits
            "archie_categories": [],  # Archie_Brain categories
        }

        # Extract git commits from timeline
        if git_timeline:
            insights["git_commits"] = git_timeline.get("recent_commits", [])
            insights["code_changes"] = git_timeline.get("modified_files", [])

        # Analyze messages for patterns
        full_text = " ".join([m.get("content", "") for m in messages])
        full_text_lower = full_text.lower()

        # Detect mistakes/errors
        error_patterns = [
            "error:",
            "exception:",
            "failed",
            "traceback",
            "bug",
            "issue",
            "problem",
            "broken",
            "fix",
        ]
        for pattern in error_patterns:
            if pattern in full_text_lower:
                insights["mistakes_found"].append({"pattern": pattern, "detected": True})

        # Detect solutions
        solution_patterns = [
            "fixed by",
            "solved by",
            "solution:",
            "the fix was",
            "resolved",
            "working now",
            "that fixed it",
        ]
        for pattern in solution_patterns:
            if pattern in full_text_lower:
                insights["solutions_learned"].append({"pattern": pattern, "detected": True})

        # Detect decisions
        decision_patterns = [
            "decided to",
            "will use",
            "going with",
            "approach:",
            "strategy:",
            "plan:",
            "implementation:",
        ]
        for pattern in decision_patterns:
            if pattern in full_text_lower:
                insights["decisions_made"].append({"pattern": pattern, "detected": True})

        # Detect TODOs
        todo_patterns = ["todo:", "need to", "should", "next step"]
        for pattern in todo_patterns:
            if pattern in full_text_lower:
                insights["todos_created"].append({"pattern": pattern, "detected": True})

        # Categorize with Archie_Brain taxonomy
        insights["archie_categories"] = self._categorize_archie_brain(full_text_lower)

        return insights

    def _categorize_archie_brain(self, text: str) -> List[str]:
        """
        Categorize content using Archie_Brain taxonomy.

        Categories:
        - development: code, bug, feature, refactor
        - infrastructure: docker, deploy, backup, database
        - ai_learning: model, prompt, training, knowledge
        - mistake_prevention: error, fix, issue, problem
        - documentation: docs, readme, guide, tutorial
        """
        categories = []

        category_keywords = {
            "development": [
                "code",
                "function",
                "class",
                "bug",
                "feature",
                "refactor",
                "implement",
                "api",
            ],
            "infrastructure": [
                "docker",
                "deploy",
                "backup",
                "database",
                "postgres",
                "compose",
                "server",
                "nginx",
            ],
            "ai_learning": [
                "model",
                "prompt",
                "training",
                "knowledge",
                "claude",
                "llm",
                "embedding",
                "ai",
            ],
            "mistake_prevention": [
                "error",
                "fix",
                "issue",
                "problem",
                "exception",
                "debug",
                "traceback",
            ],
            "documentation": [
                "docs",
                "readme",
                "guide",
                "tutorial",
                "comment",
                "docstring",
                "explain",
            ],
        }

        for category, keywords in category_keywords.items():
            if any(kw in text for kw in keywords):
                categories.append(category)

        return categories if categories else ["general"]

    def create_mistake_learned_entry(
        self, error_description: str, solution: str, context: Dict[str, Any]
    ) -> Optional[int]:
        """
        Create a mistake_learned entry when an error pattern is detected.

        Args:
            error_description: Description of the error
            solution: How it was fixed
            context: Additional context (session_id, git info, etc.)

        Returns:
            Knowledge entry ID or None
        """
        try:
            if not self.db:
                return None

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            title = f"Mistake Learned: {error_description[:100]}"
            content = f"""## Error
{error_description}

## Solution
{solution}

## Context
- Session: {context.get('session_name', 'unknown')}
- Branch: {context.get('git_branch', 'unknown')}
- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    source_type,
                    source_id,
                    memory_metadata
                ) VALUES (
                    'mistake_learned',
                    %s,
                    %s,
                    'mistake_prevention',
                    %s,
                    0.95,
                    'conversation_session',
                    %s,
                    %s
                ) RETURNING id
            """,
                (
                    title,
                    content,
                    ["mistake", "error", "solution", "learned"],
                    str(context.get("session_id", "unknown")),
                    json.dumps(
                        {
                            "auto_extracted": True,
                            "error_pattern": error_description[:200],
                            "git_branch": context.get("git_branch"),
                            "created_at": datetime.now().isoformat(),
                        }
                    ),
                ),
            )

            result = cur.fetchone()
            knowledge_id = result["id"]

            self.db.commit()
            cur.close()

            logger.info(f"[Conversation Processor] Created mistake_learned entry #{knowledge_id}")
            return knowledge_id

        except Exception as e:
            logger.error(f"[Conversation Processor] Error creating mistake entry: {e}")
            if self.db:
                self.db.rollback()
            return None

    def _create_immediate_knowledge_entry(
        self,
        session_id: int,
        session_name: str,
        git_branch: str,
        phase: str,
        topic: str,
        summary: str,
        tags: List[str],
    ) -> Optional[int]:
        """
        Create immediate knowledge_base entry for conversation.

        This creates a searchable entry BEFORE full summarization.
        Tagged with Archie_Brain categories for unified search.
        """
        try:
            cur = self.db.cursor(cursor_factory=RealDictCursor)

            # Calculate importance based on phase and topic
            importance = 0.7  # Default
            if "phase" in phase.lower() and phase.lower() != "general":
                importance = 0.85  # Phase work is important
            if topic in ["bug_fix", "deployment", "knowledge"]:
                importance = 0.90  # Critical topics

            # Create title
            title = f"Conversation: {session_name} ({phase})"
            if len(title) > 200:
                title = title[:197] + "..."

            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    source_type,
                    source_id,
                    memory_metadata
                ) VALUES (
                    'conversation_memory',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'conversation_session',
                    %s,
                    %s
                ) RETURNING id
            """,
                (
                    title,
                    summary,
                    topic,
                    tags,
                    importance,
                    str(session_id),
                    json.dumps(
                        {
                            "session_id": session_id,
                            "session_name": session_name,
                            "git_branch": git_branch,
                            "phase": phase,
                            "created_at": datetime.now().isoformat(),
                            "auto_generated": True,
                        }
                    ),
                ),
            )

            result = cur.fetchone()
            knowledge_id = result["id"]

            self.db.commit()
            cur.close()

            logger.info(f"[Conversation Processor] Created knowledge entry #{knowledge_id} for session #{session_id}")
            return knowledge_id

        except Exception as e:
            logger.error(f"[Conversation Processor] Error creating knowledge entry: {e}")
            if self.db:
                self.db.rollback()
            return None

    def _determine_phase(self, session_name: str, git_branch: str) -> str:
        """Determine which phase this session belongs to"""
        # Check session name and git branch for phase indicators
        text = f"{session_name} {git_branch}".lower()

        if "phase-6" in text or "phase_6" in text:
            return "Phase 6"
        elif "phase-5" in text or "phase_5" in text:
            return "Phase 5"
        elif "phase-4" in text or "phase_4" in text:
            return "Phase 4"
        elif "phase-3" in text or "phase_3" in text:
            return "Phase 3"
        elif "phase-2" in text or "phase_2" in text:
            return "Phase 2"
        elif "phase-1" in text or "phase_1" in text:
            return "Phase 1"
        else:
            return "General"

    def _determine_topic(self, session_name: str) -> str:
        """Determine primary topic based on session name"""
        name_lower = session_name.lower()

        topic_keywords = {
            "database": ["database", "db", "postgres", "sql", "migration"],
            "api": ["api", "endpoint", "route", "rest"],
            "ui": ["ui", "frontend", "template", "html", "css"],
            "deployment": ["deploy", "docker", "compose", "production"],
            "testing": ["test", "spec", "coverage"],
            "improvement": ["improvement", "enhance", "optimize"],
            "bug_fix": ["bug", "fix", "error", "issue"],
            "knowledge": ["knowledge", "brain", "memory", "learning"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in name_lower for kw in keywords):
                return topic

        return "general"

    def process_all_pending_snapshots(self) -> Dict[str, Any]:
        """
        Process all unprocessed snapshots in logs directory.

        Returns:
            Dict with processing summary
        """
        try:
            logger.info("[Conversation Processor] Processing all pending snapshots...")

            # Find all snapshot files
            snapshot_pattern = os.path.join(self.logs_dir, "snapshot_*.json")
            snapshot_files = glob.glob(snapshot_pattern)

            if not snapshot_files:
                logger.info("[Conversation Processor] No snapshots found")
                return {
                    "success": True,
                    "processed": 0,
                    "already_processed": 0,
                    "failed": 0,
                }

            processed = 0
            already_processed = 0
            failed = 0

            for snapshot_file in snapshot_files:
                result = self.process_snapshot(snapshot_file)

                if result.get("success"):
                    if result.get("already_processed"):
                        already_processed += 1
                    else:
                        processed += 1
                else:
                    failed += 1
                    logger.error(f"[Conversation Processor] Failed to process {snapshot_file}: {result.get('error')}")

            logger.info(
                f"[Conversation Processor] Processed {processed} new, {already_processed} already processed, {failed} failed"
            )

            return {
                "success": True,
                "processed": processed,
                "already_processed": already_processed,
                "failed": failed,
                "total_files": len(snapshot_files),
            }

        except Exception as e:
            logger.error(f"[Conversation Processor] Error processing snapshots: {e}")
            return {"success": False, "error": str(e)}

    def add_conversation_transcript(self, session_id: int, transcript: str, source: str = "manual") -> Dict[str, Any]:
        """
        Add full conversation transcript to existing session.

        Args:
            session_id: Session ID
            transcript: Full conversation text
            source: Source of transcript (manual, claude_api, file, etc.)

        Returns:
            Dict with update result
        """
        try:
            if not self.db:
                return {"success": False, "error": "No database connection"}

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                UPDATE conversation_sessions
                SET
                    full_transcript = %s,
                    processing_status = 'raw',
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
            """,
                (
                    transcript,
                    json.dumps(
                        {
                            "transcript_source": source,
                            "transcript_added_at": datetime.now().isoformat(),
                        }
                    ),
                    session_id,
                ),
            )

            self.db.commit()
            cur.close()

            logger.info(f"[Conversation Processor] Added transcript to session #{session_id}")

            return {
                "success": True,
                "session_id": session_id,
                "transcript_length": len(transcript),
            }

        except Exception as e:
            logger.error(f"[Conversation Processor] Error adding transcript: {e}")
            if self.db:
                self.db.rollback()
            return {"success": False, "error": str(e)}

    def get_sessions(self, limit: int = 20, status: Optional[str] = None, phase: Optional[str] = None) -> List[Dict]:
        """
        Get conversation sessions with optional filters.

        Args:
            limit: Max results
            status: Filter by processing_status
            phase: Filter by phase

        Returns:
            List of session dicts
        """
        try:
            if not self.db:
                return []

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            sql = "SELECT * FROM conversation_sessions WHERE 1=1"
            params = []

            if status:
                sql += " AND processing_status = %s"
                params.append(status)

            if phase:
                sql += " AND phase = %s"
                params.append(phase)

            sql += " ORDER BY started_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(sql, params)
            results = cur.fetchall()
            cur.close()

            return [dict(r) for r in results]

        except Exception as e:
            logger.error(f"[Conversation Processor] Error getting sessions: {e}")
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """Get conversation session statistics"""
        try:
            if not self.db:
                return {}

            cur = self.db.cursor(cursor_factory=RealDictCursor)

            cur.execute("SELECT * FROM conversation_sessions_stats")
            result = cur.fetchone()
            cur.close()

            return dict(result) if result else {}

        except Exception as e:
            logger.error(f"[Conversation Processor] Error getting statistics: {e}")
            return {}

    def summarize_and_index_session(self, session_id: int) -> Dict[str, Any]:
        """
        Summarize a conversation session and create knowledge_base entries.

        Args:
            session_id: Session ID to process

        Returns:
            Dict with processing result
        """
        try:
            if not self.db:
                return {"success": False, "error": "No database connection"}

            if not SUMMARIZER_AVAILABLE:
                logger.warning("[Conversation Processor] Summarizer not available")
                return {"success": False, "error": "Summarizer not available"}

            logger.info(f"[Conversation Processor] Summarizing session #{session_id}")

            # Get session
            cur = self.db.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM conversation_sessions WHERE id = %s", (session_id,))
            session = cur.fetchone()

            if not session:
                cur.close()
                return {"success": False, "error": "Session not found"}

            session = dict(session)

            # Check if already processed
            if session.get("processing_status") in ["summarized", "indexed"]:
                logger.info(f"[Conversation Processor] Session #{session_id} already processed")
                cur.close()
                return {"success": True, "already_processed": True}

            # Get transcript
            transcript = session.get("full_transcript")
            if not transcript:
                cur.close()
                return {"success": False, "error": "No transcript available"}

            # Update status to processing
            cur.execute(
                """
                UPDATE conversation_sessions
                SET processing_status = 'processing'
                WHERE id = %s
            """,
                (session_id,),
            )
            self.db.commit()

            # Summarize using Claude API
            summarizer = get_conversation_summarizer()
            session_metadata = {
                "session_name": session.get("session_name"),
                "git_branch": session.get("git_branch"),
                "phase": session.get("phase"),
                "primary_topic": session.get("primary_topic"),
            }

            summary_data = summarizer.summarize_conversation(transcript, session_metadata)

            # Update session with summary
            cur.execute(
                """
                UPDATE conversation_sessions
                SET
                    summary = %s,
                    key_insights = %s,
                    decisions_made = %s,
                    code_patterns_learned = %s,
                    tags = %s,
                    productivity_score = %s,
                    learning_value = %s,
                    code_quality = %s,
                    processing_status = 'summarized',
                    processed_at = NOW()
                WHERE id = %s
            """,
                (
                    summary_data.get("summary"),
                    json.dumps(summary_data.get("key_insights", [])),
                    json.dumps(summary_data.get("decisions_made", [])),
                    json.dumps(summary_data.get("code_patterns_learned", [])),
                    summary_data.get("tags", []),
                    summary_data.get("productivity_score"),
                    summary_data.get("learning_value"),
                    summary_data.get("code_quality"),
                    session_id,
                ),
            )

            self.db.commit()
            cur.close()

            logger.info(f"[Conversation Processor] Session #{session_id} summarized successfully")

            return {
                "success": True,
                "session_id": session_id,
                "summary": summary_data.get("summary"),
                "insights_count": len(summary_data.get("key_insights", [])),
                "decisions_count": len(summary_data.get("decisions_made", [])),
                "productivity_score": summary_data.get("productivity_score"),
                "learning_value": summary_data.get("learning_value"),
            }

        except Exception as e:
            logger.error(f"[Conversation Processor] Error summarizing session: {e}")
            if self.db:
                try:
                    cur = self.db.cursor()
                    cur.execute(
                        """
                        UPDATE conversation_sessions
                        SET processing_status = 'error'
                        WHERE id = %s
                    """,
                        (session_id,),
                    )
                    self.db.commit()
                    cur.close()
                except Exception:
                    pass
            return {"success": False, "error": str(e)}

    def create_knowledge_entries_from_session(self, session_id: int) -> Dict[str, Any]:
        """
        Create knowledge_base entries from summarized session.

        Creates one entry per key insight and stores references.

        Args:
            session_id: Session ID

        Returns:
            Dict with created entry IDs
        """
        try:
            if not self.db:
                return {"success": False, "error": "No database connection"}

            logger.info(f"[Conversation Processor] Creating knowledge entries for session #{session_id}")

            # Get session
            cur = self.db.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM conversation_sessions WHERE id = %s", (session_id,))
            session = cur.fetchone()

            if not session:
                cur.close()
                return {"success": False, "error": "Session not found"}

            session = dict(session)

            # Check if summarized
            if session.get("processing_status") != "summarized":
                cur.close()
                return {"success": False, "error": "Session not summarized yet"}

            # Create knowledge entry for the session summary
            entry_ids = []

            # Main session summary entry
            cur.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type,
                    title,
                    content,
                    category,
                    tags,
                    importance_score,
                    source_type,
                    source_id
                ) VALUES (
                    'conversation_memory',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'conversation_session',
                    %s
                ) RETURNING id
            """,
                (
                    f"Session: {session.get('session_name')} - {session.get('phase')}",
                    session.get("summary"),
                    session.get("primary_topic"),
                    session.get("tags", []),
                    session.get("learning_value", 0.7),  # Use learning_value as importance
                    str(session_id),
                ),
            )

            main_entry_id = cur.fetchone()["id"]
            entry_ids.append(main_entry_id)

            logger.info(f"[Conversation Processor] Created main knowledge entry #{main_entry_id}")

            # Update session with knowledge entry IDs
            cur.execute(
                """
                UPDATE conversation_sessions
                SET
                    knowledge_entries_created = %s,
                    processing_status = 'indexed'
                WHERE id = %s
            """,
                (entry_ids, session_id),
            )

            self.db.commit()
            cur.close()

            logger.info(
                f"[Conversation Processor] Created {len(entry_ids)} knowledge entries for session #{session_id}"
            )

            return {
                "success": True,
                "session_id": session_id,
                "entry_ids": entry_ids,
                "entries_created": len(entry_ids),
            }

        except Exception as e:
            logger.error(f"[Conversation Processor] Error creating knowledge entries: {e}")
            if self.db:
                self.db.rollback()
            return {"success": False, "error": str(e)}


# Singleton instance
_processor_instance = None


def get_conversation_processor(db_connection=None):
    """Get singleton conversation processor instance"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = ConversationProcessor(db_connection)
    elif db_connection is not None:
        _processor_instance.db = db_connection
    return _processor_instance


# ============================================================================
# CLI INTERFACE
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: conversation_processor.py <command> <snapshot_file>")
        print("")
        print("Commands:")
        print("  process-snapshot <file>  Process a conversation snapshot from PreCompact hook")
        print("")
        print("Example:")
        print("  python3 conversation_processor.py process-snapshot /path/to/snapshot.json")
        sys.exit(1)

    command = sys.argv[1]
    snapshot_file = sys.argv[2]

    if command == "process-snapshot":
        try:
            # Get database connection
            from database import get_db

            db = get_db()

            # Create processor
            processor = ConversationProcessor(db_connection=db)

            # Process snapshot
            result = processor.process_snapshot(snapshot_file)

            if result.get("success"):
                session_id = result.get("session_id")
                already_processed = result.get("already_processed", False)

                if already_processed:
                    print(f"✅ Session already processed: {session_id}")
                else:
                    entries_created = result.get("entries_created", 0)
                    print("✅ Processed conversation snapshot")
                    print(f"   Session ID: {session_id}")
                    print(f"   Knowledge entries created: {entries_created}")
                    print(f"   Snapshot: {snapshot_file}")

                sys.exit(0)
            else:
                error = result.get("error", "Unknown error")
                print(f"❌ Error processing snapshot: {error}")
                sys.exit(1)

        except Exception as e:
            print(f"❌ Fatal error: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

    else:
        print(f"❌ Unknown command: {command}")
        print("Run without arguments for usage help")
        sys.exit(1)
