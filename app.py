"""
SageAlpha.ai v3.0 - 2025 Flask Application
Modern Flask 3.x with Blueprints, SocketIO, and async support
"""

import io
import os
import re
from datetime import datetime
from functools import wraps
from uuid import uuid4

import pandas as pd
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from blob_utils import BlobReader
from blueprints import auth_bp, chat_bp, pdf_bp, portfolio_bp
from blueprints.auth import init_oauth
from blueprints.chat import (
    SESSIONS,
    build_session_memory_sections,
    create_session,
    create_db_session,
    extract_topic,
    get_db_session,
    get_current_user_id,
    save_message,
    update_session_title,
)
from blueprints.portfolio import (
    extract_company_from_message,
    auto_add_company_to_portfolio,
)
# Load environment variables
load_dotenv()

# ==================== Database Backend (SQLite) ====================
from db_sqlite import (
    User,
    create_tables,
    db_cursor,
    get_db_connection,
    get_user_by_id,
    init_db,
    seed_demo_users,
)
print("[startup] DB backend: SQLite")

from extractor import extract_text_from_pdf_bytes, parse_xbrl_file_to_text
from vector_store import VectorStore
from report_generator import generate_report_pdf, generate_equity_research_html

# ==================== Environment Detection ====================
IS_PRODUCTION = os.getenv("WEBSITE_SITE_NAME") is not None
IS_AZURE = IS_PRODUCTION  # Alias for clarity

# ==================== Configuration ====================
# Flask
FLASK_SECRET = os.getenv("FLASK_SECRET") or os.urandom(24).hex()
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() in ("1", "true", "yes")

# Database - PostgreSQL via psycopg2 (see db.py)
# Set DATABASE_URL env var for Azure PostgreSQL
# Format: postgresql://user:pass@host:port/dbname

# Azure Blob Storage
AZURE_BLOB_CONNECTION_STRING = os.getenv("AZURE_BLOB_CONNECTION_STRING") or os.getenv("AZURE_STORAGE_CONNECTION_STRING")

# Azure OpenAI - Only initialize if credentials present
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Azure Cognitive Search
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "azureblob-index")
AZURE_SEARCH_SEMANTIC_CONFIG = os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG")

# Redis/Celery - For background tasks
# Only use Redis if explicitly configured via environment variable
# Falls back to None (not localhost) to avoid connection errors in Azure
REDIS_URL = os.getenv("AZURE_REDIS_CONNECTION_STRING") or os.getenv("REDIS_URL")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or REDIS_URL
REDIS_AVAILABLE = REDIS_URL is not None

# Standard OpenAI (fallback for local dev)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Mock mode for testing without any API key
MOCK_LLM = os.getenv("MOCK_LLM", "false").lower() in ("1", "true", "yes")

# ==================== LLM Client with Fallback ====================
LLM_MODE = "none"  # Will be set during initialization: "azure", "openai", "mock", "none"
_llm_client = None
_search_client = None


class MockLLMClient:
    """Mock LLM client for local testing without API keys."""
    
    class MockCompletion:
        def __init__(self, content: str):
            self.message = type("Message", (), {"content": content})()
    
    class MockResponse:
        def __init__(self, content: str):
            self.choices = [MockLLMClient.MockCompletion(content)]
    
    class MockChat:
        class Completions:
            @staticmethod
            def create(model: str, messages: list, **kwargs) -> "MockLLMClient.MockResponse":
                # Extract the user's last message
                user_msg = ""
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        user_msg = msg.get("content", "")
                        break
                
                # Generate a helpful mock response
                response = f"""Hello! I'm SageAlpha running in **demo mode** (no API key configured).

Based on your question about: "{user_msg[:100]}{'...' if len(user_msg) > 100 else ''}"

Here's what I would analyze:
• Market trends and financial metrics
• Key risk factors and opportunities  
• Valuation comparisons with peers
• Recent news and SEC filings

To enable full AI analysis:
1. Set OPENAI_API_KEY in your .env file (get one free at openai.com/api-keys)
2. Or set AZURE_OPENAI_API_KEY for Azure OpenAI
3. Restart the server

This is a demo response for testing the UI flow."""
                
                return MockLLMClient.MockResponse(response)
        
        completions = Completions()
    
    chat = MockChat()


def init_llm_client():
    """Initialize LLM client with fallback: Azure OpenAI → OpenAI → Mock → None."""
    global _llm_client, LLM_MODE
    
    # Priority 1: Azure OpenAI (production)
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY:
        try:
            from openai import AzureOpenAI
            _llm_client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=AZURE_OPENAI_API_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
            )
            LLM_MODE = "azure"
            print("[startup] ✓ LLM: Azure OpenAI initialized")
            return _llm_client
        except Exception as e:
            print(f"[startup] ✗ Azure OpenAI failed: {e}")
    
    # Priority 2: Standard OpenAI (local dev with API key)
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI
            _llm_client = OpenAI(api_key=OPENAI_API_KEY)
            LLM_MODE = "openai"
            print("[startup] ✓ LLM: OpenAI initialized")
            return _llm_client
        except Exception as e:
            print(f"[startup] ✗ OpenAI failed: {e}")
    
    # Priority 3: Mock mode (for testing without any API key)
    if MOCK_LLM or (not AZURE_OPENAI_API_KEY and not OPENAI_API_KEY):
        _llm_client = MockLLMClient()
        LLM_MODE = "mock"
        print("[startup] ✓ LLM: Mock mode enabled (demo responses)")
        return _llm_client
    
    # No LLM available
    LLM_MODE = "none"
    print("[startup] ✗ LLM: No backend configured")
    return None


def get_llm_client():
    """Get the initialized LLM client."""
    global _llm_client
    if _llm_client is None:
        init_llm_client()
    return _llm_client


def get_llm_model() -> str:
    """Get the model name based on LLM mode."""
    if LLM_MODE == "azure":
        return AZURE_OPENAI_DEPLOYMENT or "gpt-4"
    elif LLM_MODE == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    else:
        return "mock-model"


def get_search_client():
    """Lazily initialize Azure Search client only when needed."""
    global _search_client
    if _search_client is None and AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
        _search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(AZURE_SEARCH_KEY),
        )
    return _search_client


def create_app(config_name: str = "default") -> Flask:
    """Application factory for Flask app."""
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.secret_key = FLASK_SECRET

    # ==================== Database Configuration ====================
    # Using pure psycopg2 with DATABASE_URL (no Flask-SQLAlchemy)
    # Database is initialized via init_db() after app creation

    # ==================== Session Configuration ====================
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # URL generation configuration
    if not IS_PRODUCTION:
        app.config["SERVER_NAME"] = "127.0.0.1:8000"
        app.config["PREFERRED_URL_SCHEME"] = "http"

    # Debug mode
    app.config["DEBUG"] = not IS_PRODUCTION

    # ==================== Initialize Extensions ====================
    # Note: No Flask-SQLAlchemy - using pure psycopg2 (see db.py)

    # CORS configuration
    CORS(
        app,
        resources={r"/api/*": {"origins": "*"}},
        supports_credentials=True,
    )

    # Rate limiting - use Redis if available, otherwise memory
    # Don't use Redis unless explicitly configured to avoid localhost errors in Azure
    if REDIS_AVAILABLE:
        rate_limit_storage = REDIS_URL
        print(f"[startup] Rate limiting: Redis")
    else:
        rate_limit_storage = "memory://"
        print("[startup] Rate limiting: In-memory (no Redis configured)")
    
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per day", "50 per hour"],
        storage_uri=rate_limit_storage,
    )

    # Login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        """Load user by ID for Flask-Login (uses psycopg2)."""
        try:
            return get_user_by_id(int(user_id))
        except Exception:
            return None

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(pdf_bp)
    app.register_blueprint(portfolio_bp)

    # Initialize OAuth providers
    init_oauth(app)

    # Context processor for version and environment
    @app.context_processor
    def inject_globals():
        return {
            "APP_VERSION": read_version(),
            "IS_PRODUCTION": IS_PRODUCTION,
        }

    # ==================== Initialize Database ====================
    # Initialize PostgreSQL with psycopg2 (creates tables, seeds demo users)
    try:
        init_db()
    except Exception as e:
        print(f"[DB][ERROR] Database initialization failed: {e!r}")
        # Continue anyway - database might come up later

    return app


def read_version() -> str:
    """Get application version."""
    v = os.getenv("SAGEALPHA_VERSION")
    if v:
        return v.strip()
    try:
        with open(os.path.join(os.path.dirname(__file__), "VERSION"), "r") as f:
            return f.read().strip()
    except Exception:
        return "3.0.0"


# Note: seed_demo_users() is now in db.py and called by init_db()


# Create app instance
app = create_app()

# Initialize SocketIO for real-time chat
socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*"
)

# Initialize Azure services
search_client = None
if AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY and AZURE_SEARCH_INDEX:
    try:
        search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX,
            credential=AzureKeyCredential(AZURE_SEARCH_KEY),
        )
        print(f"[startup] Connected to Azure Search index: {AZURE_SEARCH_INDEX}")
    except Exception as e:
        print(f"[startup] Failed to initialize SearchClient: {e}")
else:
    print("[startup] Azure Search client not initialized.")

# Initialize LLM client with fallback chain
client = init_llm_client()

# BlobReader
BLOB_CONTAINER = "nse-data-raw"
blob_reader = None
if AZURE_BLOB_CONNECTION_STRING:
    try:
        blob_reader = BlobReader(
            conn_str=AZURE_BLOB_CONNECTION_STRING, container=BLOB_CONTAINER
        )
        print("[startup] BlobReader initialized.")
    except Exception as e:
        print(f"[startup][WARN] Failed to initialize BlobReader: {e!r}")
else:
    print("[WARN] Missing AZURE_BLOB_CONNECTION_STRING.")

# Vector store
VECTOR_STORE_DIR = "vector_store_data"
os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
vs = VectorStore(store_dir=VECTOR_STORE_DIR)

# Upload directory
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== Helper Functions ====================


def strip_markdown(text: str) -> str:
    """Remove markdown formatting from text."""
    if not text:
        return text
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"(^|\n)#{1,6}\s*", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    text = re.sub(r"(^|\n)[\-\*\+]\s+", r"\1", text)
    text = re.sub(r"\n[-*_]{3,}\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def search_azure(query_text: str, top_k: int = 5) -> list:
    """Search Azure Cognitive Search index."""
    if not search_client or not query_text:
        return []

    search_kwargs = {"search_text": query_text, "top": top_k}

    if AZURE_SEARCH_SEMANTIC_CONFIG:
        search_kwargs["query_type"] = "semantic"
        search_kwargs["semantic_configuration_name"] = AZURE_SEARCH_SEMANTIC_CONFIG

    try:
        results = search_client.search(**search_kwargs)
    except Exception as e:
        print(f"[azure] search error: {e}")
        return []

    output = []
    for r in results:
        content_parts = []
        for field_name in ["merged_content", "content", "imageCaption"]:
            val = r.get(field_name)
            if isinstance(val, list):
                val = " ".join(str(x) for x in val)
            if val:
                content_parts.append(str(val))
        text = "\n".join(content_parts) or ""
        meta = {
            "source": r.get("metadata_storage_path") or r.get("source"),
            "people": r.get("people"),
            "organizations": r.get("organizations"),
            "locations": r.get("locations"),
        }
        doc_id = r.get("id") or r.get("metadata_storage_path") or ""
        score = float(r.get("@search.score", 0.0))
        output.append({"doc_id": doc_id, "text": text, "meta": meta, "score": score})

    return output


def build_hybrid_messages(
    user_msg: str, retrieved_docs: list, extra_system_msgs: list | None = None
) -> list:
    """Build messages for hybrid RAG."""
    relevance_threshold = 0.35
    relevant_docs = [
        r for r in retrieved_docs if r.get("score", 0.0) >= relevance_threshold
    ]

    if relevant_docs:
        context_chunks = [
            f"Source: {r['meta'].get('source', r['doc_id'])}\n{r['text']}"
            for r in relevant_docs
            if r.get("text")
        ]
        context_text = "\n\n".join(context_chunks)[:6000]
    else:
        context_text = ""

    system_prompt = (
        "You are SageAlpha, a financial assistant powered by SageAlpha.ai.\n"
        "Use this logic:\n"
        "1. If the Context contains useful information, use it to answer.\n"
        "2. If the Context is empty or not relevant, answer using your own knowledge.\n"
        "3. Be precise and financially accurate.\n"
        "4. Respond in clear plain text only. Do not use markdown formatting.\n"
    )

    messages = [{"role": "system", "content": system_prompt}]

    if extra_system_msgs:
        messages.extend(extra_system_msgs)

    messages.append({"role": "system", "content": f"Context:\n{context_text}"})
    messages.append({"role": "user", "content": user_msg})

    return messages


# ==================== Routes ====================


@app.route("/")
def home():
    """Main chat page."""
    if REQUIRE_AUTH and not (
        hasattr(current_user, "is_authenticated") and current_user.is_authenticated
    ):
        return redirect("/login")
    return render_template(
        "index.html", 
        APP_VERSION=read_version(),
        LLM_MODE=LLM_MODE,
        LLM_READY=LLM_MODE != "none",
    )


@app.route("/api/status")
def api_status():
    """Return API status including LLM availability."""
    return jsonify({
        "status": "ok",
        "version": read_version(),
        "llm_mode": LLM_MODE,
        "llm_ready": LLM_MODE != "none",
        "search_ready": search_client is not None,
        "blob_ready": blob_reader is not None,
    })


@app.route("/chat", methods=["POST"])
def chat():
    """Chat endpoint for AI conversation with database persistence."""
    if REQUIRE_AUTH:
        if not (
            (
                hasattr(current_user, "is_authenticated")
                and current_user.is_authenticated
            )
            or session.get("user")
        ):
            return jsonify({"error": "Authentication required"}), 401

    # Get LLM client (always available due to mock fallback)
    llm = get_llm_client()
    if llm is None:
        return jsonify({"error": "LLM backend not configured"}), 500

    payload = request.get_json(silent=True) or {}
    user_msg = (payload.get("message") or "").strip()
    chat_session_id = payload.get("session_id")  # Optional session ID
    
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    # Get current user ID for database operations
    user_id = get_current_user_id()
    
    # =====================================================
    # DATABASE-BACKED MESSAGE PERSISTENCE
    # =====================================================
    if user_id:
        # Check if we have a session_id, if not create one
        if not chat_session_id:
            db_session = None
        else:
            db_session = get_db_session(chat_session_id, user_id)
        
        if not db_session:
            # Create new session in database
            chat_session_id = create_db_session(user_id, "New Chat")
        
        # Save user message to database
        if chat_session_id:
            save_message(chat_session_id, user_id, "user", user_msg)
            
            # Update session title if this is the first message
            if db_session and (not db_session.get("title") or db_session.get("title") == "New Chat"):
                new_title = user_msg[:60] + ("..." if len(user_msg) > 60 else "")
                update_session_title(chat_session_id, user_id, new_title)

    # Session management (Flask session for backward compatibility)
    if "history" not in session:
        session["history"] = [
            {
                "role": "system",
                "content": "I'm SageAlpha, a financial assistant powered by SageAlpha.ai.",
            }
        ]
    if "sections" not in session:
        session["sections"] = []
    if "current_topic" not in session:
        session["current_topic"] = ""

    history = session["history"]
    sections = session["sections"]
    last_topic = session.get("current_topic", "")

    current_topic = extract_topic(user_msg, last_topic)
    session["current_topic"] = current_topic or ""

    history.append({"role": "user", "content": user_msg})

    session_memory_text = build_session_memory_sections(sections, current_topic)
    extra_system_msgs = []
    if session_memory_text:
        extra_system_msgs.append(
            {
                "role": "system",
                "content": f"Session memory (previous Q&A sections):\n{session_memory_text}",
            }
        )

    top_k = int(payload.get("top_k", 5))
    retrieved = search_azure(user_msg, top_k)
    if not retrieved and search_client is None:
        retrieved = vs.search(user_msg, k=top_k)

    messages = build_hybrid_messages(user_msg, retrieved, extra_system_msgs)

    try:
        response = llm.chat.completions.create(
            model=get_llm_model(),
            messages=messages,
            max_tokens=800,
            temperature=0.0,
            top_p=0.95,
        )
        ai_msg = response.choices[0].message.content

        history.append({"role": "assistant", "content": ai_msg})
        sections.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "query": user_msg,
                "answer": ai_msg,
            }
        )
        session["history"] = history
        session["sections"] = sections

        # =====================================================
        # SAVE ASSISTANT MESSAGE TO DATABASE
        # =====================================================
        if user_id and chat_session_id:
            save_message(chat_session_id, user_id, "assistant", ai_msg)

        # =====================================================
        # AUTO-ADD COMPANY TO PORTFOLIO
        # Detect if user is researching a company and auto-add it
        # =====================================================
        if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
            company_info = extract_company_from_message(user_msg)
            if company_info:
                company_name, ticker = company_info
                portfolio_item_id = auto_add_company_to_portfolio(
                    current_user.id, company_name, ticker
                )
                if portfolio_item_id:
                    print(f"[chat] Auto-added company to portfolio: {company_name} ({ticker})")

        sources = [
            {
                "doc_id": r["doc_id"],
                "source": r["meta"].get("source"),
                "score": float(r["score"]),
            }
            for r in retrieved
        ]

        msg_id = str(uuid4())
        message_obj = {"id": msg_id, "role": "assistant", "content": ai_msg}

        return jsonify(
            {
                "id": msg_id,
                "response": ai_msg,
                "message": message_obj,
                "data": message_obj,
                "sources": sources,
                "session_id": chat_session_id,  # Return session ID for client
            }
        )

    except Exception as e:
        error_msg = f"Backend error: {e!s}"
        msg_id = str(uuid4())
        message_obj = {"id": msg_id, "role": "assistant", "content": error_msg}
        print(f"[chat][ERROR] {e!r}")
        return (
            jsonify(
                {
                    "id": msg_id,
                    "response": error_msg,
                    "message": message_obj,
                    "data": message_obj,
                    "sources": [],
                    "error": str(e),
                }
            ),
            500,
        )


@app.route("/chat_session", methods=["POST"])
def chat_session():
    """Chat endpoint with session management and database persistence."""
    if REQUIRE_AUTH:
        if not (
            hasattr(current_user, "is_authenticated") and current_user.is_authenticated
        ):
            return jsonify({"error": "Authentication required"}), 401

    # Get LLM client (always available due to mock fallback)
    llm = get_llm_client()
    if llm is None:
        return jsonify({"error": "LLM backend not configured"}), 500

    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id")
    user_msg = (payload.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    # Get current user ID for database operations
    user_id = get_current_user_id()
    
    # =====================================================
    # DATABASE-BACKED SESSION MANAGEMENT
    # =====================================================
    if user_id:
        # Check if session exists in database
        db_session = get_db_session(session_id, user_id) if session_id else None
        
        if not db_session:
            # Create new session in database
            session_id = create_db_session(user_id, "New Chat")
            if not session_id:
                return jsonify({"error": "Failed to create session"}), 500
        
        # Save user message to database
        save_message(session_id, user_id, "user", user_msg)
        
        # Update session title if this is the first message
        if db_session and (not db_session.get("title") or db_session.get("title") == "New Chat"):
            # Use first 60 chars of user message as title
            new_title = user_msg[:60] + ("..." if len(user_msg) > 60 else "")
            update_session_title(session_id, user_id, new_title)
    
    # Keep in-memory session for backward compatibility
    if session_id and session_id in SESSIONS:
        s = SESSIONS[session_id]
        if s.get("owner") != getattr(current_user, "username", None):
            return jsonify({"error": "Session not found"}), 404
    else:
        s = create_session("New chat", owner=getattr(current_user, "username", None))
        if not session_id:
            session_id = s["id"]

    s["messages"].append({"role": "user", "content": user_msg, "meta": {}})

    last_topic = s.get("current_topic", "")
    current_topic = extract_topic(user_msg, last_topic)
    s["current_topic"] = current_topic or ""

    session_memory_text = build_session_memory_sections(
        s.get("sections", []), current_topic
    )
    extra_system_msgs = []
    if session_memory_text:
        extra_system_msgs.append(
            {
                "role": "system",
                "content": f"Session memory (previous Q&A sections):\n{session_memory_text}",
            }
        )

    top_k = int(payload.get("top_k", 5))
    retrieved = search_azure(user_msg, top_k)
    if not retrieved and search_client is None:
        retrieved = vs.search(user_msg, k=top_k)

    # ==================== PDF INTENT DETECTION ====================
    # Broadened keywords to capture "financial questions" as requested
    pdf_keywords = ["pdf", "generate report", "download report", "export", "html report", "research report", "html file", "html"]
    financial_keywords = ["research", "paper", "study", "article", "document", "analysis", "valuation", "forecast", "outlook", "financials", "thesis", "summary"]

    # Check if user wants a report (either explicitly asking for PDF/HTML or asking for deep analysis)
    wants_pdf = any(k in user_msg.lower() for k in pdf_keywords)
    is_research_request = wants_pdf or any(k in user_msg.lower() for k in financial_keywords)

    # Extract company name
    # Extract company name (Robust extraction)
    # 1. Broad regex to find all "for/about X" patterns
    matches = re.findall(r'(?:for|on|about|concerning|pertaining|covering)\s+([a-zA-Z0-9\s&]+?)(?=[^\w]|$)', user_msg, re.I)

    # 2. Filter matches
    blocklist = {"generating", "research", "report", "creating", "making", "download", "pdf", "html", "code", "analysis", "paper", "version", "of", "a", "an", "the"}

    company = None
    if matches:
        # Iterate backwards to prioritize the last mentioned entity (usually the target)
        for m in reversed(matches):
            candidate = m.strip().lower()
            words = candidate.split()
            if not words: continue
            if candidate in blocklist: continue
            if words[0] in blocklist: continue
            company = m.strip()
            break

    # If no company found via regex, try to use the whole message if it's short and looks like a company name
    if not company and len(user_msg) < 50 and not any(k in user_msg.lower() for k in ["generate", "report", "pdf", "html"]):
        company = user_msg.strip()

    # Default to "Unknown Company" if still not found, or handle it in generation
    if not company:
        company = "Target Company"

    ticker = company.split()[-1].upper() if ' ' in company else company.upper()

    pdf_data = {}

    if is_research_request:
        # SKIP LLM call entirely for reports
        # Construct context text for the report generator
        relevance_threshold = 0.35
        relevant_docs = [
            r for r in retrieved if r.get("score", 0.0) >= relevance_threshold
        ]
        context_text = ""
        if relevant_docs:
            context_chunks = [
                f"Source: {r['meta'].get('source', r['doc_id'])}\n{r['text']}"
                for r in relevant_docs
                if r.get("text")
            ]
            context_text = "\n\n".join(context_chunks)[:10000]

        # Generate dynamic equity research report using LLM for content only
        report_html = generate_equity_research_html(llm, get_llm_model(), company, user_msg, context_text)

        # FORCE set report_title
        report_title = f"{company.replace(' ', '_').upper()} Research Report"

        pdf_data = {"html": report_html, "title": report_title}

        # Fixed message preventing LLM hallucinations
        ai_msg = f"Your research report for {company} is ready. Click the download button to get the PDF."
    else:
        messages = build_hybrid_messages(user_msg, retrieved, extra_system_msgs)

    try:
        resp = llm.chat.completions.create(
            model=get_llm_model(),
            messages=messages,
            max_tokens=800,
            temperature=0.0,
            top_p=0.95,
        )
        ai_msg = resp.choices[0].message.content
    except Exception as e:
        ai_msg = f"Backend error: {e!s}"

    # Common code for both research requests and regular chat
    s["messages"].append({"role": "assistant", "content": ai_msg, "meta": {}})
    s["sections"].append(
        {
            "timestamp": datetime.utcnow().isoformat(),
            "query": user_msg,
            "answer": ai_msg,
        }
    )

    # =====================================================
    # SAVE ASSISTANT MESSAGE TO DATABASE
    # =====================================================
    if user_id and session_id:
        save_message(session_id, user_id, "assistant", ai_msg)

    # =====================================================
    # AUTO-ADD COMPANY TO PORTFOLIO
    # Detect if user is researching a company and auto-add it
    # =====================================================
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        company_info = extract_company_from_message(user_msg)
        if company_info:
            company_name, ticker = company_info
            portfolio_item_id = auto_add_company_to_portfolio(
                current_user.id, company_name, ticker
            )
            if portfolio_item_id:
                print(f"[chat_session] Auto-added company to portfolio: {company_name} ({ticker})")

    sources = [
        {
            "doc_id": r["doc_id"],
            "source": r["meta"].get("source"),
            "score": float(r["score"]),
        }
        for r in retrieved
    ]

    return jsonify(
        {
            "session_id": session_id,
            "response": ai_msg,
            "sources": sources,
            "pdf_data": pdf_data,
        }
    )


@app.route("/query", methods=["POST"])
def query():
    """Query endpoint for RAG search."""
    # Get LLM client (always available due to mock fallback)
    llm = get_llm_client()
    if llm is None:
        return jsonify({"error": "LLM backend not configured"}), 500

    payload = request.get_json(silent=True) or {}
    q = (payload.get("q") or "").strip()
    if not q:
        return jsonify({"error": "Empty query"}), 400

    top_k = int(payload.get("top_k", 5))
    fetch_pdf = bool(payload.get("fetch_pdf", True))

    results = search_azure(q, top_k)
    if not results and search_client is None:
        results = vs.search(q, k=top_k)

    for r in results:
        att = r.get("meta", {}).get("attachment") or ""
        if not fetch_pdf or not att or not blob_reader:
            continue
        try:
            if att.startswith("https://"):
                pdf_bytes = blob_reader.download_blob_url_to_bytes(att)
            else:
                pdf_bytes = blob_reader.download_blob_to_bytes(att)
            extracted = extract_text_from_pdf_bytes(pdf_bytes)
            meta = {"source": f"pdf_temp:{att}", "attachment": att}
            temp_doc_id = f"temp_pdf::{att}"
            try:
                vs.add_temporary_document(doc_id=temp_doc_id, text=extracted, meta=meta)
            except Exception:
                pass
        except Exception as e:
            print(f"[query] failed to download/extract {att}: {e}")

    if search_client:
        final_results = search_azure(q, top_k)
    else:
        final_results = vs.search(q, k=top_k)

    messages = build_hybrid_messages(q, final_results)

    try:
        resp = llm.chat.completions.create(
            model=get_llm_model(),
            messages=messages,
            max_tokens=800,
            temperature=0.0,
            top_p=0.95,
        )
        ai_msg = resp.choices[0].message.content or ""
        ai_msg = strip_markdown(ai_msg)
        try:
            vs.clear_temporary_documents()
        except Exception:
            pass

        sources = [
            {
                "doc_id": r["doc_id"],
                "source": r["meta"].get("source"),
                "score": float(r.get("score", 0.0)),
            }
            for r in final_results
        ]
        return jsonify({"answer": ai_msg, "sources": sources})
    except Exception as e:
        try:
            vs.clear_temporary_documents()
        except Exception:
            pass
        print(f"[query][ERROR] {e!r}")
        return jsonify({"error": str(e)}), 500


@app.route("/report-html", methods=["GET"])
def report_html():
    """Return report HTML fragment for client-side PDF generation."""
    try:
        html = render_template("sagealpha_reports.html")

        wants_fragment = False
        if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
            wants_fragment = True
        else:
            accept_hdr = (request.headers.get("Accept") or "").lower()
            if accept_hdr.startswith("*/*") or "text/html" not in accept_hdr:
                wants_fragment = True

        if not wants_fragment:
            resp = make_response(html)
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp

        head_match = re.search(
            r"<head[^>]*>([\s\S]*?)</head>", html, flags=re.IGNORECASE
        )
        body_match = re.search(
            r"<body[^>]*>([\s\S]*?)</body>", html, flags=re.IGNORECASE
        )

        head_html = head_match.group(1) if head_match else ""
        body_html = body_match.group(1) if body_match else html

        style_blocks = re.findall(
            r"<style[^>]*>([\s\S]*?)</style>", head_html, flags=re.IGNORECASE
        )

        link_tags = re.findall(
            r"<link[^>]*rel=[\"']stylesheet[\"'][^>]*>",
            head_html,
            flags=re.IGNORECASE,
        )

        injected_print_css = """
        <style>
        #sagealpha-report-fragment, #sagealpha-report-fragment * {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            box-sizing: border-box;
        }
        #sagealpha-report-fragment .container { background: white !important; }
        #sagealpha-report-fragment { width: 1200px; max-width: 1200px; margin: 0 auto; }
        #sagealpha-report-fragment a { color: inherit; text-decoration: none; }
        </style>
        """

        combined_styles = ""
        if style_blocks:
            combined_styles = "<style>" + "\n".join(style_blocks) + "</style>"

        links_html = "\n".join(link_tags)

        fragment = (
            f"<div id='sagealpha-report-fragment' style='background:white;'>\n"
            f"{injected_print_css}\n"
            f"{combined_styles}\n"
            f"{links_html}\n"
            f"{body_html}\n"
            f"</div>"
        )

        resp = make_response(fragment)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    except Exception as e:
        print(f"[report-html][ERROR] {e!r}")
        return jsonify({"error": f"Failed to render report HTML: {e!s}"}), 500


@app.route("/refresh", methods=["POST"])
def refresh():
    """Refresh index endpoint."""
    if REQUIRE_AUTH:
        if not (
            (
                hasattr(current_user, "is_authenticated")
                and current_user.is_authenticated
            )
            or session.get("user")
        ):
            return jsonify({"error": "Authentication required"}), 401
    return jsonify({"status": "refreshed"})


@app.route("/test_search")
def test_search():
    """Test Azure Search endpoint."""
    if not search_client:
        return jsonify(
            {"status": "error", "message": "search_client is None."}
        )
    q = request.args.get("q", "cupid")
    try:
        results = search_client.search(search_text=q, top=3)
        items = []
        for r in results:
            items.append(
                {
                    "id": r.get("id"),
                    "score": r.get("@search.score"),
                    "path": r.get("metadata_storage_path"),
                    "content_preview": (
                        r.get("content") or r.get("merged_content") or ""
                    )[:200],
                }
            )
        return jsonify({"status": "ok", "query": q, "results": items})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler."""
    code = 500
    if isinstance(e, HTTPException):
        code = e.code
    print(f"[ERROR] {e!r}")
    return jsonify({"error": str(e)}), code


# ==================== File Upload ====================

# Store uploaded documents per session for RAG context
SESSION_DOCUMENTS: dict = {}  # session_id -> [{"doc_id": str, "filename": str, "text": str}]


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list:
    """Split text into overlapping chunks for better retrieval."""
    if not text:
        return []
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
        if start < 0:
            start = 0
        if end >= len(text):
            break
    return chunks


@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Handle PDF file upload, extract text, and index for RAG.
    Works in both local mode and with Azure services.
    """
    if REQUIRE_AUTH:
        if not (
            (hasattr(current_user, "is_authenticated") and current_user.is_authenticated)
            or session.get("user")
        ):
            return jsonify({"error": "Authentication required"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    session_id = request.form.get("session_id") or str(uuid4())

    # Check file type
    allowed_extensions = {".pdf", ".txt", ".md", ".csv"}
    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in allowed_extensions:
        return jsonify({"error": f"File type {file_ext} not supported. Use: {', '.join(allowed_extensions)}"}), 400

    try:
        # Read file content
        file_bytes = file.read()
        file_size = len(file_bytes)

        # Save file locally
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        saved_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)
        
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        print(f"[upload] Saved file: {file_path} ({file_size} bytes)")

        # Extract text based on file type
        extracted_text = ""
        if file_ext == ".pdf":
            from extractor import extract_text_from_pdf_bytes
            extracted_text = extract_text_from_pdf_bytes(file_bytes)
        elif file_ext in {".txt", ".md"}:
            extracted_text = file_bytes.decode("utf-8", errors="ignore")
        elif file_ext == ".csv":
            import pandas as pd
            df = pd.read_csv(io.BytesIO(file_bytes))
            extracted_text = df.to_string()

        if not extracted_text.strip():
            return jsonify({"error": "Could not extract text from file"}), 400

        print(f"[upload] Extracted {len(extracted_text)} characters from {filename}")

        # Chunk the text for better retrieval
        chunks = chunk_text(extracted_text, chunk_size=1500, overlap=200)
        print(f"[upload] Created {len(chunks)} chunks")

        # Generate unique document ID
        doc_id = f"upload_{session_id}_{timestamp}_{filename}"

        # Index chunks in vector store
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            meta = {
                "source": f"upload:{filename}",
                "filename": filename,
                "session_id": session_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
            try:
                vs.add_document(doc_id=chunk_id, text=chunk, meta=meta)
            except Exception as e:
                print(f"[upload] Failed to index chunk {i}: {e}")

        # Store document info for session
        if session_id not in SESSION_DOCUMENTS:
            SESSION_DOCUMENTS[session_id] = []
        
        SESSION_DOCUMENTS[session_id].append({
            "doc_id": doc_id,
            "filename": filename,
            "file_path": file_path,
            "text_preview": extracted_text[:500],
            "chunk_count": len(chunks),
            "uploaded_at": datetime.utcnow().isoformat(),
        })

        # Save vector store
        vs.save_index()

        return jsonify({
            "success": True,
            "filename": filename,
            "doc_id": doc_id,
            "chunks": len(chunks),
            "characters": len(extracted_text),
            "session_id": session_id,
            "url": f"/uploads/{saved_filename}",
            "message": f"Successfully processed {filename} ({len(chunks)} chunks indexed)",
        })

    except Exception as e:
        print(f"[upload][ERROR] {e!r}")
        return jsonify({"error": f"Upload failed: {e!s}"}), 500


@app.route("/uploads/<filename>")
def serve_upload(filename):
    """Serve uploaded files."""
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/session/<session_id>/documents", methods=["GET"])
def get_session_documents(session_id):
    """Get list of documents uploaded to a session."""
    docs = SESSION_DOCUMENTS.get(session_id, [])
    return jsonify({"documents": docs})


# ==================== WebSocket Events ====================


@socketio.on("connect")
def handle_connect():
    """Handle WebSocket connection."""
    print(f"[ws] Client connected: {request.sid}")
    emit("connected", {"status": "ok", "sid": request.sid})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket disconnection."""
    print(f"[ws] Client disconnected: {request.sid}")


@socketio.on("join")
def handle_join(data):
    """Join a chat room."""
    room = data.get("room")
    if room:
        join_room(room)
    emit("joined", {"room": room}, room=room)


@socketio.on("chat_message")
def handle_chat_message(data):
    """Handle real-time chat messages via WebSocket with database persistence."""
    # Get LLM client (always available due to mock fallback)
    llm = get_llm_client()
    if llm is None:
        emit("error", {"message": "LLM backend not configured"})
        return

    user_msg = (data.get("message") or "").strip()
    session_id = data.get("session_id")

    if not user_msg:
        emit("error", {"message": "Empty message"})
        return

    # Get current user ID for database operations
    user_id = get_current_user_id()

    # =====================================================
    # DATABASE-BACKED SESSION MANAGEMENT (WebSocket)
    # =====================================================
    if user_id:
        # Check if session exists in database
        db_session = get_db_session(session_id, user_id) if session_id else None
        
        if not db_session:
            # Create new session in database
            session_id = create_db_session(user_id, "New Chat")
        
        # Save user message to database
        if session_id:
            save_message(session_id, user_id, "user", user_msg)
            
            # Update session title if this is the first message
            if db_session and (not db_session.get("title") or db_session.get("title") == "New Chat"):
                new_title = user_msg[:60] + ("..." if len(user_msg) > 60 else "")
                update_session_title(session_id, user_id, new_title)

    # Emit typing indicator
    emit("typing", {"status": True})

    try:
        top_k = int(data.get("top_k", 5))
        retrieved = search_azure(user_msg, top_k)
        if not retrieved and search_client is None:
            retrieved = vs.search(user_msg, k=top_k)

        messages = build_hybrid_messages(user_msg, retrieved)

        response = llm.chat.completions.create(
            model=get_llm_model(),
            messages=messages,
            max_tokens=800,
            temperature=0.0,
            top_p=0.95,
        )
        ai_msg = response.choices[0].message.content

        # =====================================================
        # SAVE ASSISTANT MESSAGE TO DATABASE (WebSocket)
        # =====================================================
        if user_id and session_id:
            save_message(session_id, user_id, "assistant", ai_msg)

        # =====================================================
        # AUTO-ADD COMPANY TO PORTFOLIO (WebSocket handler)
        # Detect if user is researching a company and auto-add it
        # =====================================================
        if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
            company_info = extract_company_from_message(user_msg)
            if company_info:
                company_name, ticker = company_info
                portfolio_item_id = auto_add_company_to_portfolio(
                    current_user.id, company_name, ticker
                )
                if portfolio_item_id:
                    print(f"[ws] Auto-added company to portfolio: {company_name} ({ticker})")

        sources = [
            {"doc_id": r["doc_id"], "source": r["meta"].get("source")}
            for r in retrieved
        ]

    except Exception as e:
        emit("typing", {"status": False})
        emit("error", {"message": f"Backend error: {e!s}"})
        print(f"[ws][ERROR] {e!r}")
        return

    emit("typing", {"status": False})
    emit(
        "chat_response",
        {
            "id": str(uuid4()),
            "response": ai_msg,
            "sources": sources,
            "session_id": session_id,
            "pdf_data": pdf_data,
        },
    )

    # TODO: Add proper exception handling


# ==================== Entry Point ====================

def find_available_port(host: str = "0.0.0.0", start_port: int = 8000, max_port: int = 8010) -> int:
    """Find an available port in the given range (development only)."""
    import socket
    import time
    
    for try_port in range(start_port, max_port + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, try_port))
            sock.close()
            if try_port != start_port:
                print(f"[startup] Port {start_port} busy, using port {try_port}")
            return try_port
        except OSError:
            sock.close()
            print(f"[startup] Port {try_port} is busy, trying next...")
            time.sleep(1)
    
    return None


@app.route("/generate-pdf", methods=["POST"])
def generate_pdf_endpoint():
    """
    Endpoint to generate a PDF from provided content.
    Expects JSON: { "content": "...", "title": "..." }
    """
    data = request.get_json() or {}
    content = data.get("content", "").strip()
    title = data.get("title", "SageAlpha Report")

    if not content:
        return jsonify({"error": "No content provided"}), 400

    try:
        pdf_buffer = generate_report_pdf(content, title=title)
        filename_safe = re.sub(r'[^\w\-_]', '_', title) + "_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf"

        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=filename_safe,
            mimetype="application/pdf"
        )
    except Exception as e:
        print(f"PDF Generation Error: {e}")
        return jsonify({"error": str(e)}), 500


# ==================== CHAT-ONLY REPORT GENERATION ====================
# This route generates reports from chat WITHOUT touching the portfolio

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "generated_reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


@app.route("/chat/create-report", methods=["POST"])
def chat_create_report():
    """
    Generate a quick equity research report for a company.
    This does NOT add the company to the portfolio.
    
    Expects JSON: { "company_name": "...", "ticker": "..." (optional) }
    Returns: { "success": true, "message": "...", "download_url": "...", "report_id": "..." }
    """
    data = request.get_json() or {}
    company_name = (data.get("company_name") or "").strip()
    ticker = (data.get("ticker") or "").strip()
    
    if not company_name:
        return jsonify({"error": "Company name is required"}), 400
    
    # Get LLM client
    llm = get_llm_client()
    if llm is None:
        return jsonify({"error": "LLM backend not available"}), 500
    
    try:
        print(f"[chat/create-report] Generating report for: {company_name}")
        
        # Generate report HTML using existing LLM function
        user_message = f"Generate an equity research report for {company_name}"
        
        # Try to get some context from vector store
        context_text = ""
        try:
            if vs:
                retrieved = vs.search(company_name, top_k=3)
                context_chunks = [
                    r.get("text", "")
                    for r in retrieved
                    if r.get("text")
                ]
                context_text = "\n\n".join(context_chunks)[:5000]
        except Exception as e:
            print(f"[chat/create-report] Context retrieval warning: {e}")
        
        # Generate the report HTML
        report_html = generate_equity_research_html(
            llm, 
            get_llm_model(), 
            company_name, 
            user_message, 
            context_text
        )
        
        # Generate unique report ID and filename
        report_id = f"{company_name.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        html_filename = f"{report_id}.html"
        html_filepath = os.path.join(REPORTS_DIR, html_filename)
        
        # Save the HTML report
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(report_html)
        
        print(f"[chat/create-report] Report saved: {html_filepath}")
        
        # Build download URL
        download_url = f"/reports/download/{report_id}"
        
        # Build chat message
        message = f"✅ Your research report for **{company_name}** is ready!\n\n📄 [Download Report as PDF]({download_url})"
        
        return jsonify({
            "success": True,
            "message": message,
            "download_url": download_url,
            "report_id": report_id,
            "company_name": company_name
        })
        
    except Exception as e:
        print(f"[chat/create-report] Error: {e}")
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500


@app.route("/reports/download/<report_id>")
def download_report(report_id):
    """
    Download a generated report as PDF.
    The report_id corresponds to the HTML file saved in generated_reports folder.
    """
    # Sanitize report_id to prevent path traversal
    safe_report_id = re.sub(r'[^\w\-_]', '_', report_id)
    html_filename = f"{safe_report_id}.html"
    html_filepath = os.path.join(REPORTS_DIR, html_filename)
    
    if not os.path.exists(html_filepath):
        return jsonify({"error": "Report not found"}), 404
    
    try:
        # Read the HTML content
        with open(html_filepath, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        # Check if user wants HTML or PDF
        # Default to HTML download for simplicity (PDF conversion requires additional libs)
        wants_pdf = request.args.get("format", "html").lower() == "pdf"
        
        if wants_pdf:
            # Try to generate PDF using ReportLab (simple text extraction)
            # For better PDF, the frontend can use html2pdf.js
            try:
                # Extract text from HTML for simple PDF
                import re as regex
                text_content = regex.sub(r'<[^>]+>', '', html_content)
                text_content = regex.sub(r'\s+', ' ', text_content).strip()
                
                # Extract company name from report_id
                company_for_title = report_id.replace('_', ' ').title().split()[0] if report_id else "Company"
                
                pdf_buffer = generate_report_pdf(text_content[:8000], title=f"SageAlpha Research - {company_for_title}")
                
                return send_file(
                    pdf_buffer,
                    as_attachment=True,
                    download_name=f"SageAlpha_{safe_report_id}.pdf",
                    mimetype="application/pdf"
                )
            except Exception as pdf_err:
                print(f"[reports/download] PDF generation fallback to HTML: {pdf_err}")
                # Fall through to HTML
        
        # Return HTML (client can use html2pdf.js for better PDF)
        response = make_response(html_content)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Content-Disposition"] = f'attachment; filename="SageAlpha_{safe_report_id}.html"'
        return response
        
    except Exception as e:
        print(f"[reports/download] Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/reports/view/<report_id>")
def view_report(report_id):
    """
    View a generated report in the browser (HTML).
    """
    safe_report_id = re.sub(r'[^\w\-_]', '_', report_id)
    html_filename = f"{safe_report_id}.html"
    html_filepath = os.path.join(REPORTS_DIR, html_filename)
    
    if not os.path.exists(html_filepath):
        return jsonify({"error": "Report not found"}), 404
    
    try:
        with open(html_filepath, "r", encoding="utf-8") as f:
            html_content = f.read()
        
        return html_content, 200, {"Content-Type": "text/html; charset=utf-8"}
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"[startup] Local dev server on http://127.0.0.1:{port}/login")
    socketio.run(
        app,
        host="127.0.0.1",
        port=port,
        debug=True,
        allow_unsafe_werkzeug=True
    )
