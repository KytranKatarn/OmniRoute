#!/usr/bin/env python3
"""
Conversation Capture Script
Extracts full conversation transcript from Claude Code history.jsonl
Integrated with pre-compact hook for automatic memory preservation
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

CLAUDE_HISTORY = Path.home() / ".claude" / "history.jsonl"


def get_current_session_id() -> Optional[str]:
    """Get the current Claude Code session ID from environment"""
    # Claude Code provides this in hooks
    return os.environ.get("HOOK_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")


def extract_session_conversation(session_id: Optional[str] = None) -> List[Dict]:
    """
    Extract all messages for a specific session from history.jsonl

    Args:
        session_id: Session UUID (if None, uses latest session)

    Returns:
        List of conversation messages with metadata
    """
    if not CLAUDE_HISTORY.exists():
        print(f"❌ Claude history not found: {CLAUDE_HISTORY}")
        return []

    messages = []
    current_session = session_id

    with open(CLAUDE_HISTORY, "r") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())

                # Track current session if not specified
                if not current_session and "sessionId" in entry:
                    current_session = entry["sessionId"]

                # Filter by session ID
                if session_id and entry.get("sessionId") != session_id:
                    continue

                # Extract message
                if "display" in entry:
                    messages.append(
                        {
                            "content": entry["display"],
                            "timestamp": entry.get("timestamp"),
                            "session_id": entry.get("sessionId"),
                            "project": entry.get("project"),
                            "pasted_contents": entry.get("pastedContents"),
                        }
                    )

            except json.JSONDecodeError as e:
                print(f"⚠️ Skipping malformed JSON line: {e}")
                continue

    return messages


def format_conversation_transcript(messages: List[Dict]) -> str:
    """
    Format messages into readable transcript

    Returns conversation as markdown with timestamps
    """
    if not messages:
        return "No messages found"

    transcript = []
    transcript.append("# Conversation Transcript")
    transcript.append(f"**Session ID:** {messages[0]['session_id']}")
    transcript.append(f"**Project:** {messages[0].get('project', 'Unknown')}")
    transcript.append(f"**Captured:** {datetime.now().isoformat()}")
    transcript.append(f"**Messages:** {len(messages)}")
    transcript.append("")
    transcript.append("---")
    transcript.append("")

    for i, msg in enumerate(messages, 1):
        timestamp = msg.get("timestamp", "Unknown")
        content = msg["content"]

        transcript.append(f"## Message {i}")
        transcript.append(f"**Time:** {timestamp}")
        transcript.append("")
        transcript.append(content)
        transcript.append("")
        transcript.append("---")
        transcript.append("")

    return "\n".join(transcript)


def save_conversation_snapshot(
    messages: List[Dict],
    output_dir: str = "/mnt/archie_brain/conversation_logs",
    metadata: Optional[Dict] = None,
) -> str:
    """
    Save conversation transcript and metadata to snapshot file

    Returns path to saved snapshot file
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_file = os.path.join(output_dir, f"snapshot_{timestamp}.json")
    transcript_file = os.path.join(output_dir, f"transcript_{timestamp}.md")

    # Format transcript
    transcript = format_conversation_transcript(messages)

    # Create enhanced snapshot with full content
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "session_id": messages[0]["session_id"] if messages else "unknown",
        "project": messages[0].get("project") if messages else "unknown",
        "message_count": len(messages),
        "transcript_file": transcript_file,
        "compact_type": "auto",
        "context_usage": "~80%",
        "git_branch": metadata.get("git_branch") if metadata else "unknown",
        "git_commit": metadata.get("git_commit") if metadata else "unknown",
        "working_directory": (metadata.get("working_directory") if metadata else os.getcwd()),
        "conversation_summary": (messages[0]["content"][:200] + "..." if messages else ""),
        "messages": messages,  # Full conversation data
    }

    # Save transcript as markdown
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(transcript)

    # Save snapshot with full data
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    print("✅ Conversation captured:")
    print(f"   Snapshot: {snapshot_file}")
    print(f"   Transcript: {transcript_file}")
    print(f"   Messages: {len(messages)}")

    return snapshot_file


def main():
    """
    Main entry point for conversation capture

    Usage:
        python3 capture_conversation.py [session_id] [output_dir]
    """
    # Get parameters
    session_id = sys.argv[1] if len(sys.argv) > 1 else get_current_session_id()
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/mnt/archie_brain/conversation_logs"

    print("📸 Capturing conversation...")
    print(f"   Session ID: {session_id or 'latest'}")
    print(f"   Output: {output_dir}")
    print("")

    # Extract conversation
    messages = extract_session_conversation(session_id)

    if not messages:
        print("⚠️ No messages found for session")
        return 1

    # Gather metadata from environment (provided by hook)
    metadata = {
        "git_branch": os.environ.get("HOOK_GIT_BRANCH", "unknown"),
        "git_commit": os.environ.get("HOOK_GIT_COMMIT", "unknown"),
        "working_directory": os.environ.get("HOOK_CWD", os.getcwd()),
    }

    # Save snapshot
    snapshot_file = save_conversation_snapshot(messages, output_dir, metadata)

    print("")
    print("✅ Conversation capture complete!")
    print(f"   Ready for processing: {snapshot_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
