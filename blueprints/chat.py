"""
SageAlpha.ai Chat Blueprint
Real-time chat with WebSocket support via Flask-SocketIO
Persistent chat history stored in SQLite database
"""

import os
import re
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, List, Dict, Any

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for, flash
from flask_login import current_user, login_required

# Import database functions
from db_sqlite import db_cursor, get_db_connection

chat_bp = Blueprint("chat", __name__)

# In-memory session store (kept for backward compatibility, will be phased out)
SESSIONS: dict = {}


# ==================== Database Helper Functions ====================

def create_db_session(user_id: int, title: str = "New Chat") -> Optional[str]:
    """
    Create a new chat session in the database.
    
    Args:
        user_id: The ID of the user creating the session
        title: Initial title for the session
    
    Returns:
        The session ID (UUID string) or None on failure
    """
    session_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at, current_topic)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (session_id, user_id, title, now, now, "")
            )
        return session_id
    except Exception as e:
        print(f"[chat] Error creating session: {e}")
        return None


def get_db_session(session_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a chat session from the database.
    
    Args:
        session_id: The session UUID
        user_id: The ID of the requesting user (for ownership check)
    
    Returns:
        Session dict or None if not found/unauthorized
    """
    try:
        with db_cursor(commit=False) as cur:
            cur.execute(
                """SELECT id, user_id, title, created_at, updated_at, current_topic
                   FROM chat_sessions
                   WHERE id = %s AND user_id = %s""",
                (session_id, user_id)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return None
    except Exception as e:
        print(f"[chat] Error getting session: {e}")
        return None


def get_user_sessions(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Get all chat sessions for a user, ordered by most recent.
    
    Args:
        user_id: The user ID
        limit: Maximum number of sessions to return
    
    Returns:
        List of session dicts
    """
    try:
        with db_cursor(commit=False) as cur:
            cur.execute(
                """SELECT cs.id, cs.title, cs.created_at, cs.updated_at,
                          (SELECT COUNT(*) FROM messages WHERE session_id = cs.id) as message_count
                   FROM chat_sessions cs
                   WHERE cs.user_id = %s
                   ORDER BY cs.updated_at DESC
                   LIMIT %s""",
                (user_id, limit)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"[chat] Error getting user sessions: {e}")
        return []


def get_session_messages(session_id: str, user_id: int) -> List[Dict[str, Any]]:
    """
    Get all messages for a session.
    
    Args:
        session_id: The session UUID
        user_id: The user ID (for ownership check)
    
    Returns:
        List of message dicts ordered by timestamp
    """
    try:
        with db_cursor(commit=False) as cur:
            # First verify session ownership
            cur.execute(
                "SELECT 1 FROM chat_sessions WHERE id = %s AND user_id = %s",
                (session_id, user_id)
            )
            if not cur.fetchone():
                return []
            
            # Get messages
            cur.execute(
                """SELECT id, role, content, timestamp
                   FROM messages
                   WHERE session_id = %s AND user_id = %s
                   ORDER BY timestamp ASC""",
                (session_id, user_id)
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"[chat] Error getting messages: {e}")
        return []


def save_message(session_id: str, user_id: int, role: str, content: str) -> Optional[int]:
    """
    Save a message to the database.
    
    Args:
        session_id: The session UUID
        user_id: The user ID
        role: Message role ('user' or 'assistant')
        content: Message content
    
    Returns:
        The message ID or None on failure
    """
    now = datetime.now(timezone.utc).isoformat()
    
    try:
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO messages (session_id, user_id, role, content, timestamp)
                   VALUES (%s, %s, %s, %s, %s)""",
                (session_id, user_id, role, content, now)
            )
            message_id = cur.lastrowid
            
            # Update session's updated_at timestamp
            cur.execute(
                "UPDATE chat_sessions SET updated_at = %s WHERE id = %s",
                (now, session_id)
            )
            
        return message_id
    except Exception as e:
        print(f"[chat] Error saving message: {e}")
        return None


def update_session_title(session_id: str, user_id: int, title: str) -> bool:
    """
    Update a session's title.
    
    Args:
        session_id: The session UUID
        user_id: The user ID (for ownership check)
        title: New title
    
    Returns:
        True on success, False on failure
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                """UPDATE chat_sessions SET title = %s, updated_at = %s
                   WHERE id = %s AND user_id = %s""",
                (title, datetime.now(timezone.utc).isoformat(), session_id, user_id)
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"[chat] Error updating session title: {e}")
        return False


def delete_db_session(session_id: str, user_id: int) -> bool:
    """
    Delete a chat session and all its messages.
    
    Args:
        session_id: The session UUID
        user_id: The user ID (for ownership check)
    
    Returns:
        True on success, False on failure
    """
    try:
        with db_cursor() as cur:
            # Delete messages first (due to foreign key)
            cur.execute(
                "DELETE FROM messages WHERE session_id = %s AND user_id = %s",
                (session_id, user_id)
            )
            # Delete session
            cur.execute(
                "DELETE FROM chat_sessions WHERE id = %s AND user_id = %s",
                (session_id, user_id)
            )
            return cur.rowcount > 0
    except Exception as e:
        print(f"[chat] Error deleting session: {e}")
        return False


def require_auth(f):
    """Decorator to check authentication."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        require_auth_env = os.getenv("REQUIRE_AUTH", "true").lower() in (
            "1",
            "true",
            "yes",
        )
        if require_auth_env:
            if not (
                (
                    hasattr(current_user, "is_authenticated")
                    and current_user.is_authenticated
                )
                or session.get("user")
            ):
                return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated


def get_current_user_id() -> Optional[int]:
    """Get the current user's ID safely."""
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        return current_user.id
    return None


def create_session(title: str = "New chat", owner: str | None = None) -> dict:
    """Create a new chat session (legacy in-memory version for backward compatibility)."""
    sid = str(uuid4())
    now = datetime.utcnow().isoformat()
    SESSIONS[sid] = {
        "id": sid,
        "title": title or "New chat",
        "created": now,
        "owner": owner,
        "messages": [],
        "sections": [],
        "current_topic": "",
    }
    return SESSIONS[sid]


def extract_topic(user_msg: str, last_topic: str | None = None) -> str | None:
    """Extract conversation topic from user message."""
    if not user_msg:
        return last_topic

    text = user_msg.strip().lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    if not tokens:
        return last_topic

    question_starts = {
        "who",
        "what",
        "which",
        "when",
        "where",
        "why",
        "how",
        "give",
        "tell",
        "show",
        "explain",
        "owner",
        "ceo",
        "chairman",
        "md",
        "director",
    }
    if tokens[0] in question_starts:
        return last_topic

    if len(tokens) <= 4:
        return text

    return last_topic


def build_session_memory_sections(
    sections: list,
    current_topic: str | None,
    limit: int = 5,
    max_chars: int = 1500,
) -> str:
    """Build session memory from previous Q&A sections."""
    if not sections:
        return ""

    normalized_topic = (current_topic or "").lower().strip()
    filtered = []

    if normalized_topic:
        for s in sections:
            q = (s.get("query") or "").lower()
            a = (s.get("answer") or "").lower()
            if normalized_topic in q or normalized_topic in a:
                filtered.append(s)

    if not filtered:
        filtered = sections[-limit:]
    else:
        filtered = filtered[-limit:]

    parts = []
    for s in filtered:
        parts.append(
            f"[{s.get('timestamp', '')}] Q: {s.get('query', '')}\nA: {s.get('answer', '')}"
        )

    memory_text = "\n\n".join(parts)
    return memory_text[:max_chars]


@chat_bp.route("/sessions", methods=["GET"])
@require_auth
def list_sessions():
    """List all chat sessions for current user from database."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"sessions": []})
    
    # Get sessions from database
    db_sessions = get_user_sessions(user_id, limit=30)
    
    # Format for frontend compatibility
    out = []
    for s in db_sessions:
        out.append({
            "id": s["id"],
            "title": s.get("title") or "New Chat",
            "created": s.get("created_at") or s.get("updated_at"),
            "updated": s.get("updated_at"),
            "message_count": s.get("message_count", 0),
        })
    
    return jsonify({"sessions": out})


@chat_bp.route("/sessions", methods=["POST"])
@require_auth
def create_session_route():
    """Create a new chat session in the database."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    data = request.get_json(silent=True) or {}
    title = data.get("title") or "New Chat"
    
    # Create session in database
    session_id = create_db_session(user_id, title)
    if not session_id:
        return jsonify({"error": "Failed to create session"}), 500
    
    # Return in format expected by frontend
    now = datetime.now(timezone.utc).isoformat()
    return jsonify({
        "session": {
            "id": session_id,
            "title": title,
            "created": now,
            "messages": [],
        }
    }), 201


@chat_bp.route("/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session(session_id: str):
    """Get a specific chat session with its messages from database."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    # Get session from database
    db_session = get_db_session(session_id, user_id)
    if not db_session:
        return jsonify({"error": "Session not found"}), 404
    
    # Get messages for this session
    messages = get_session_messages(session_id, user_id)
    
    # Format for frontend compatibility
    formatted_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]
    
    return jsonify({
        "session": {
            "id": db_session["id"],
            "title": db_session.get("title") or "New Chat",
            "created": db_session.get("created_at"),
            "messages": formatted_messages,
        }
    })


@chat_bp.route("/sessions/<session_id>/rename", methods=["POST"])
@require_auth
def rename_session(session_id: str):
    """Rename a chat session in the database."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    # Verify session exists and belongs to user
    db_session = get_db_session(session_id, user_id)
    if not db_session:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    
    if title:
        update_session_title(session_id, user_id, title)
        db_session["title"] = title
    
    return jsonify({
        "session": {
            "id": db_session["id"],
            "title": db_session.get("title") or "New Chat",
            "created": db_session.get("created_at"),
        }
    })


@chat_bp.route("/sessions/<session_id>/delete", methods=["POST", "DELETE"])
@require_auth
def delete_session(session_id: str):
    """Delete a chat session from the database."""
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    if delete_db_session(session_id, user_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Session not found or already deleted"}), 404


@chat_bp.route("/reset_history", methods=["POST"])
@require_auth
def reset_history():
    """Clear chat history from session."""
    session.pop("history", None)
    session.pop("sections", None)
    session.pop("current_topic", None)
    return jsonify({"status": "cleared"})


# ==================== Page Routes ====================

@chat_bp.route("/chat/new")
@login_required
def new_chat_page():
    """Create a new chat session and redirect to it."""
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to start a new chat.", "warning")
        return redirect(url_for("auth.login"))
    
    # Create new session in database
    session_id = create_db_session(user_id, "New Chat")
    if not session_id:
        flash("Failed to create new chat session.", "error")
        return redirect(url_for("index"))
    
    # Redirect to the new session
    return redirect(url_for("chat.chat_page", session_id=session_id))


@chat_bp.route("/chat/<session_id>")
@login_required
def chat_page(session_id: str):
    """Render the chat page for a specific session."""
    from app import read_version, LLM_MODE, get_llm_client
    
    user_id = get_current_user_id()
    if not user_id:
        flash("Please log in to view chat history.", "warning")
        return redirect(url_for("auth.login"))
    
    # Verify session belongs to user
    db_session = get_db_session(session_id, user_id)
    if not db_session:
        flash("Chat session not found.", "error")
        return redirect(url_for("index"))
    
    # Get messages for this session
    messages = get_session_messages(session_id, user_id)
    
    # Check LLM status
    llm_ready = get_llm_client() is not None
    
    return render_template(
        "index.html",
        APP_VERSION=read_version(),
        LLM_MODE=LLM_MODE,
        LLM_READY=llm_ready,
        initial_session_id=session_id,
        initial_messages=messages,
    )

