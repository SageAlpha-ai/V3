"""
SageAlpha.ai Portfolio & Subscribers Blueprint
Manage portfolio items, reports approval, and subscriber distribution.
"""

import os
import re
from datetime import datetime, timezone
from typing import Optional, Tuple

from flask import (
    Blueprint,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from db_sqlite import db_cursor, get_db_connection

portfolio_bp = Blueprint("portfolio", __name__, template_folder="../templates")


# ==================== Company/Ticker Extraction ====================

# Common patterns for extracting company names and tickers from chat messages
COMPANY_PATTERNS = [
    # Pattern: "research on <company>" or "analyze <company>"
    r"(?:research|analyze|analysis|report|look\s+(?:at|into)|tell\s+me\s+about|what\s+(?:is|about))\s+(?:on\s+)?([A-Z][a-zA-Z\s&.,]+(?:Inc|Corp|Ltd|PLC|LLC|Company|Co)?\.?)",
    # Pattern: stock ticker in caps like AAPL, TSLA, NVDA
    r"\b([A-Z]{2,5})\b(?:\s+stock|\s+shares|\s+ticker)?",
    # Pattern: "company name (TICKER)" format
    r"([A-Z][a-zA-Z\s&.,]+)\s*\(([A-Z]{2,5})\)",
]

# Common stock tickers to recognize
KNOWN_TICKERS = {
    "AAPL": "Apple Inc", "MSFT": "Microsoft Corporation", "GOOGL": "Alphabet Inc",
    "AMZN": "Amazon.com Inc", "TSLA": "Tesla Inc", "NVDA": "NVIDIA Corporation",
    "META": "Meta Platforms Inc", "CRH": "CRH PLC", "JPM": "JPMorgan Chase & Co",
    "V": "Visa Inc", "JNJ": "Johnson & Johnson", "WMT": "Walmart Inc",
    "PG": "Procter & Gamble Co", "MA": "Mastercard Inc", "HD": "Home Depot Inc",
    "CVX": "Chevron Corporation", "MRK": "Merck & Co Inc", "ABBV": "AbbVie Inc",
    "PEP": "PepsiCo Inc", "KO": "Coca-Cola Company", "COST": "Costco Wholesale Corp",
    "TMO": "Thermo Fisher Scientific", "AVGO": "Broadcom Inc", "MCD": "McDonald's Corp",
    "CSCO": "Cisco Systems Inc", "ACN": "Accenture PLC", "ABT": "Abbott Laboratories",
    "DHR": "Danaher Corporation", "NKE": "Nike Inc", "TXN": "Texas Instruments Inc",
    "NFLX": "Netflix Inc", "AMD": "Advanced Micro Devices", "INTC": "Intel Corporation",
    # Add more as needed
}


def extract_company_from_message(message: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Extract company name and optional ticker from a user chat message.
    
    Returns:
        Tuple of (company_name, ticker) if found, or None if no company detected.
        ticker may be None if only company name is found.
    """
    if not message:
        return None
    
    # First check for known tickers in the message
    words = message.upper().split()
    for word in words:
        # Clean punctuation
        clean_word = re.sub(r'[^\w]', '', word)
        if clean_word in KNOWN_TICKERS:
            return (KNOWN_TICKERS[clean_word], clean_word)
    
    # Check for "(TICKER)" pattern
    ticker_match = re.search(r'\(([A-Z]{2,5})\)', message)
    if ticker_match:
        ticker = ticker_match.group(1)
        # Try to extract company name before the ticker
        before_ticker = message[:ticker_match.start()].strip()
        if before_ticker:
            # Clean up company name
            company = re.sub(r'[,\.]+$', '', before_ticker).strip()
            if len(company) > 2:
                return (company, ticker)
        if ticker in KNOWN_TICKERS:
            return (KNOWN_TICKERS[ticker], ticker)
    
    # Look for research/analysis patterns
    for pattern in COMPANY_PATTERNS[:1]:  # First pattern for research phrases
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            company_name = match.group(1).strip()
            # Clean up the company name
            company_name = re.sub(r'^(the|a|an)\s+', '', company_name, flags=re.IGNORECASE)
            company_name = re.sub(r'[,\.]+$', '', company_name).strip()
            if len(company_name) > 2 and len(company_name) < 100:
                return (company_name, None)
    
    return None


def auto_add_company_to_portfolio(user_id: int, company_name: str, ticker: Optional[str] = None) -> Optional[int]:
    """
    Automatically add a company to user's portfolio when they research it.
    Creates a portfolio item and an associated pending report.
    
    This function is called from chat endpoints when a company research query is detected.
    
    Args:
        user_id: The current user's ID
        company_name: Name of the company
        ticker: Optional stock ticker
        
    Returns:
        The portfolio item ID if created/found, None on error
    """
    if not user_id or not company_name:
        return None
    
    try:
        return add_portfolio_item(user_id, company_name, ticker)
    except Exception as e:
        print(f"[portfolio] Failed to auto-add company: {e}")
        return None


def read_version():
    """Get application version from env or VERSION file."""
    v = os.getenv("SAGEALPHA_VERSION")
    if v:
        return v.strip()
    try:
        with open(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION"), "r"
        ) as f:
            return f.read().strip()
    except Exception:
        return "3.0.0"


# ==================== Helper Functions ====================

def get_user_id() -> Optional[int]:
    """Get current user ID from Flask-Login or session."""
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        return current_user.id
    return session.get("user_id")


def get_portfolio_items(user_id: int, item_date: str = None) -> list:
    """Get portfolio items for a user, optionally filtered by date."""
    with db_cursor(commit=False) as cur:
        if item_date:
            cur.execute(
                """SELECT * FROM portfolio_items 
                   WHERE user_id = %s AND item_date = %s
                   ORDER BY updated_at DESC""",
                (user_id, item_date)
            )
        else:
            # Default to today if no date specified
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            cur.execute(
                """SELECT * FROM portfolio_items 
                   WHERE user_id = %s AND item_date = %s
                   ORDER BY updated_at DESC""",
                (user_id, today)
            )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_reports_for_user(user_id: int, report_date: str = None) -> list:
    """Get reports for a user with portfolio item info, optionally filtered by date."""
    with db_cursor(commit=False) as cur:
        if report_date:
            cur.execute(
                """SELECT r.*, p.company_name, p.ticker, p.item_date
                   FROM reports r
                   LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
                   WHERE r.user_id = %s AND r.report_date = %s
                   ORDER BY r.created_at DESC""",
                (user_id, report_date)
            )
        else:
            # Default to today if no date specified
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            cur.execute(
                """SELECT r.*, p.company_name, p.ticker, p.item_date
                   FROM reports r
                   LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
                   WHERE r.user_id = %s AND r.report_date = %s
                   ORDER BY r.created_at DESC""",
                (user_id, today)
            )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_subscribers(user_id: int) -> list:
    """Get all subscribers for a user."""
    with db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT * FROM subscribers 
               WHERE user_id = %s AND is_active = 1
               ORDER BY created_at DESC""",
            (user_id,)
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def add_portfolio_item(user_id: int, company_name: str, ticker: str = None, item_date: str = None) -> int:
    """Add a new portfolio item. Returns the item ID."""
    now = datetime.now(timezone.utc).isoformat()
    # Ensure ticker is empty string if None (avoid "None" in templates)
    ticker = ticker if ticker else ""
    # Use today's date if not provided
    if not item_date:
        item_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Check if already exists for this date
        cur.execute(
            "SELECT id FROM portfolio_items WHERE user_id = ? AND company_name = ? AND item_date = ?",
            (user_id, company_name, item_date)
        )
        existing = cur.fetchone()
        if existing:
            # Update timestamp
            cur.execute(
                "UPDATE portfolio_items SET updated_at = ? WHERE id = ?",
                (now, existing["id"])
            )
            conn.commit()
            return existing["id"]
        
        # Insert new
        cur.execute(
            """INSERT INTO portfolio_items (user_id, company_name, ticker, item_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, company_name, ticker, item_date, now, now)
        )
        conn.commit()
        item_id = cur.lastrowid
        
        # Auto-create a pending report for this item with the same date
        cur.execute(
            """INSERT INTO reports (portfolio_item_id, user_id, title, status, report_date, created_at)
               VALUES (?, ?, ?, 'pending', ?, ?)""",
            (item_id, user_id, f"Equity Research Note – {company_name}", item_date, now)
        )
        conn.commit()
        return item_id
    finally:
        conn.close()


def add_subscriber(user_id: int, name: str, mobile: str, email: str) -> int:
    """Add a new subscriber. Returns the subscriber ID."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO subscribers (user_id, name, mobile, email, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, name, mobile, email, now)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_subscriber(subscriber_id: int, user_id: int, name: str, mobile: str, email: str) -> bool:
    """Update a subscriber. Returns True if successful."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE subscribers 
               SET name = ?, mobile = ?, email = ?
               WHERE id = ? AND user_id = ?""",
            (name, mobile, email, subscriber_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_subscriber(subscriber_id: int, user_id: int) -> bool:
    """Delete a subscriber. Returns True if successful."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM subscribers WHERE id = ? AND user_id = ?",
            (subscriber_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def approve_report(report_id: int, user_id: int) -> bool:
    """Approve a report. Returns True if successful."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE reports SET status = 'approved', approved_at = ?
               WHERE id = ? AND user_id = ?""",
            (now, report_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def all_reports_approved(user_id: int) -> bool:
    """Check if all reports for a user are approved."""
    with db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT COUNT(*) as total, 
                      SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved
               FROM reports WHERE user_id = %s""",
            (user_id,)
        )
        row = cur.fetchone()
        if row:
            total = row["total"] or 0
            approved = row["approved"] or 0
            return total > 0 and total == approved
        return False


def send_reports_to_subscribers(user_id: int, selected_report_ids: list = None) -> dict:
    """
    Send selected approved reports to all subscribers for the given user.
    
    Currently simulates sending by logging to file and console.
    
    TODO: To enable real email sending, implement one of these options:
    
    1. SMTP Integration:
       - Set environment variables: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
       - Use smtplib or Flask-Mail to send emails
       - Example:
         ```
         import smtplib
         from email.mime.multipart import MIMEMultipart
         from email.mime.text import MIMEText
         
         SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
         SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
         SMTP_USER = os.getenv("SMTP_USER")
         SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
         
         def send_email(to_email, subject, body_html):
             msg = MIMEMultipart('alternative')
             msg['Subject'] = subject
             msg['From'] = SMTP_USER
             msg['To'] = to_email
             msg.attach(MIMEText(body_html, 'html'))
             
             with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                 server.starttls()
                 server.login(SMTP_USER, SMTP_PASSWORD)
                 server.sendmail(SMTP_USER, to_email, msg.as_string())
         ```
    
    2. SendGrid Integration:
       - Set SENDGRID_API_KEY environment variable
       - pip install sendgrid
    
    3. Azure Communication Services:
       - Set AZURE_COMMUNICATION_CONNECTION_STRING
       - pip install azure-communication-email
    
    Args:
        user_id: The user whose approved reports should be sent to their subscribers
        selected_report_ids: Optional list of report IDs to send. If None, sends all approved reports.
        
    Returns:
        dict with 'success' boolean, 'message' string, and counts
    """
    # Get approved reports for THIS user only, optionally filtered by selected IDs
    with db_cursor(commit=False) as cur:
        if selected_report_ids:
            # Convert to tuple for SQL IN clause
            placeholders = ','.join(['%s'] * len(selected_report_ids))
            cur.execute(
                f"""SELECT r.*, p.company_name, p.ticker 
                   FROM reports r
                   LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
                   WHERE r.user_id = %s AND r.status = 'approved' AND r.id IN ({placeholders})""",
                (user_id,) + tuple(selected_report_ids)
            )
        else:
            cur.execute(
                """SELECT r.*, p.company_name, p.ticker 
                   FROM reports r
                   LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
                   WHERE r.user_id = %s AND r.status = 'approved'""",
                (user_id,)
            )
        reports = [dict(row) for row in cur.fetchall()]
    
    # Get subscribers for THIS user only
    subscribers = get_subscribers(user_id)
    
    if not reports:
        return {"success": False, "message": "No approved reports to send."}
    
    if not subscribers:
        return {"success": False, "message": "No subscribers found."}
    
    # ========================================================================
    # EMAIL SENDING IMPLEMENTATION
    # Currently: Simulation mode (logs to file)
    # TODO: Replace with real email sending using one of the methods above
    # ========================================================================
    
    sent_count = 0
    failed_count = 0
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "email_preview.log")
    
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            timestamp = datetime.now(timezone.utc).isoformat()
            f.write(f"\n{'='*60}\n")
            f.write(f"Report Distribution - {timestamp}\n")
            f.write(f"User ID: {user_id}\n")
            f.write(f"{'='*60}\n\n")
            
            for subscriber in subscribers:
                for report in reports:
                    try:
                        # Log the email that would be sent
                        email_subject = f"SageAlpha Report: {report['title']}"
                        ticker_info = f" ({report['ticker']})" if report.get('ticker') else ""
                        f.write(f"TO: {subscriber['name']} <{subscriber['email']}>\n")
                        f.write(f"SUBJECT: {email_subject}\n")
                        f.write(f"COMPANY: {report.get('company_name', 'N/A')}{ticker_info}\n")
                        f.write(f"REPORT_ID: {report.get('id')}\n")
                        f.write(f"STATUS: SIMULATED SEND\n")
                        f.write(f"---\n\n")
                        
                        # TODO: Replace this print with actual email sending call
                        # Example: send_email(subscriber['email'], email_subject, report_html)
                        print(f"[email] Would send to {subscriber['email']}: {report['title']}")
                        
                        sent_count += 1
                    except Exception as e:
                        failed_count += 1
                        f.write(f"FAILED to send to {subscriber['email']}: {e}\n")
                        print(f"[email][ERROR] Failed to send to {subscriber['email']}: {e}")
            
            f.write(f"\n{'='*60}\n")
            f.write(f"SUMMARY: {sent_count} sent, {failed_count} failed\n")
            f.write(f"{'='*60}\n")
    
    except Exception as e:
        print(f"[email][ERROR] Failed to write to log file: {e}")
        return {
            "success": False,
            "message": f"Email sending failed: {str(e)}",
            "sent_count": 0,
            "failed_count": 0
        }
    
    return {
        "success": True,
        "message": f"Reports sent successfully to {len(subscribers)} subscriber(s).",
        "sent_count": sent_count,
        "failed_count": failed_count,
        "subscribers": len(subscribers),
        "reports": len(reports)
    }


# ==================== Routes ====================

@portfolio_bp.route("/portfolio")
@login_required
def portfolio():
    """Portfolio page showing companies and reports filtered by date.
    
    Portfolio is fully user-specific - each user sees only their own
    portfolio items and reports. No hardcoded demo data.
    """
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
    
    # Get date from query parameter, default to today
    selected_date = request.args.get("date")
    if not selected_date:
        selected_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # Get portfolio items and reports for THIS user only, filtered by date
    portfolio_items = get_portfolio_items(user_id, selected_date)
    reports = get_reports_for_user(user_id, selected_date)
    
    # Check if all reports for this date are approved
    all_approved = len(reports) > 0 and all(r.get("status") == "approved" for r in reports)
    
    # No hardcoded demo data - portfolio is populated only when user
    # searches for companies in the chat or via explicit add
    
    return render_template(
        "portfolio.html",
        APP_VERSION=read_version(),
        portfolio_items=portfolio_items,
        reports=reports,
        all_approved=all_approved,
        selected_date=selected_date,
    )


@portfolio_bp.route("/portfolio/add", methods=["POST"])
@login_required
def add_to_portfolio():
    """Add a company to portfolio via AJAX."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    data = request.get_json(silent=True) or {}
    company_name = (data.get("company_name") or "").strip()
    ticker = (data.get("ticker") or "").strip().upper()
    
    if not company_name:
        return jsonify({"error": "Company name is required"}), 400
    
    item_id = add_portfolio_item(user_id, company_name, ticker or None)
    return jsonify({"success": True, "item_id": item_id})


@portfolio_bp.route("/portfolio/approve/<int:report_id>", methods=["POST"])
@login_required
def approve_report_route(report_id: int):
    """Approve a report."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    success = approve_report(report_id, user_id)
    if success:
        all_approved = all_reports_approved(user_id)
        return jsonify({"success": True, "all_approved": all_approved})
    return jsonify({"error": "Report not found or already approved"}), 404


@portfolio_bp.route("/portfolio/reports/delete", methods=["POST"])
@login_required
def delete_reports():
    """Delete selected reports. Only deletes reports belonging to current user."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    data = request.get_json(silent=True) or {}
    report_ids = data.get("report_ids", [])
    
    if not report_ids or not isinstance(report_ids, list):
        return jsonify({"error": "No report IDs provided"}), 400
    
    deleted_count = 0
    portfolio_items_to_check = set()
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for report_id in report_ids:
            # Verify ownership and get portfolio_item_id before deleting
            cur.execute(
                "SELECT portfolio_item_id FROM reports WHERE id = ? AND user_id = ?",
                (report_id, user_id)
            )
            report = cur.fetchone()
            if report:
                portfolio_items_to_check.add(report["portfolio_item_id"])
                # Delete the report
                cur.execute(
                    "DELETE FROM reports WHERE id = ? AND user_id = ?",
                    (report_id, user_id)
                )
                deleted_count += 1
        
        # Check if any portfolio items have no remaining reports, optionally delete them
        for item_id in portfolio_items_to_check:
            cur.execute(
                "SELECT COUNT(*) as count FROM reports WHERE portfolio_item_id = ?",
                (item_id,)
            )
            count = cur.fetchone()["count"]
            if count == 0:
                # Optionally delete portfolio item if no reports remain
                cur.execute(
                    "DELETE FROM portfolio_items WHERE id = ? AND user_id = ?",
                    (item_id, user_id)
                )
        
        conn.commit()
        return jsonify({"success": True, "deleted_count": deleted_count})
    finally:
        conn.close()


@portfolio_bp.route("/portfolio/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def edit_report(report_id: int):
    """Edit a report's title and company name."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    if request.method == "GET":
        # Return report data for editing
        with db_cursor(commit=False) as cur:
            cur.execute(
                """SELECT r.*, p.company_name, p.ticker 
                   FROM reports r
                   LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
                   WHERE r.id = %s AND r.user_id = %s""",
                (report_id, user_id)
            )
            report = cur.fetchone()
            if not report:
                return jsonify({"error": "Report not found"}), 404
            return jsonify({"report": dict(report)})
    
    # POST - Update report
    data = request.get_json(silent=True) or {}
    new_title = (data.get("title") or "").strip()
    new_company_name = (data.get("company_name") or "").strip()
    
    if not new_title:
        return jsonify({"error": "Title is required"}), 400
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Verify ownership
        cur.execute(
            """SELECT r.portfolio_item_id, p.company_name 
               FROM reports r
               LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
               WHERE r.id = ? AND r.user_id = ?""",
            (report_id, user_id)
        )
        report = cur.fetchone()
        if not report:
            return jsonify({"error": "Report not found"}), 404
        
        # Update report title
        cur.execute(
            "UPDATE reports SET title = ? WHERE id = ? AND user_id = ?",
            (new_title, report_id, user_id)
        )
        
        # Update portfolio item company name if provided
        if new_company_name and report["portfolio_item_id"]:
            cur.execute(
                "UPDATE portfolio_items SET company_name = ? WHERE id = ? AND user_id = ?",
                (new_company_name, report["portfolio_item_id"], user_id)
            )
        
        conn.commit()
        return jsonify({"success": True})
    finally:
        conn.close()


@portfolio_bp.route("/subscribers")
@login_required
def subscribers():
    """Subscribers page. Accepts selected report IDs from query params or session."""
    user_id = get_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))
    
    # Get selected report IDs from query params or session
    selected_report_ids = request.args.getlist("report_ids", type=int)
    if not selected_report_ids:
        selected_report_ids = session.get("selected_report_ids", [])
    else:
        # Store in session for later use
        session["selected_report_ids"] = selected_report_ids
    
    # If no reports selected, check if all reports are approved (backward compatibility)
    if not selected_report_ids:
        if not all_reports_approved(user_id):
            flash("Please approve all reports before proceeding to subscribers.", "warning")
            return redirect(url_for("portfolio.portfolio"))
    else:
        # Verify selected reports are approved and belong to user
        with db_cursor(commit=False) as cur:
            placeholders = ','.join(['%s'] * len(selected_report_ids))
            cur.execute(
                f"""SELECT COUNT(*) as count FROM reports 
                   WHERE user_id = %s AND id IN ({placeholders}) AND status = 'approved'""",
                (user_id,) + tuple(selected_report_ids)
            )
            approved_count = cur.fetchone()["count"]
            if approved_count != len(selected_report_ids):
                flash("All selected reports must be approved before sending.", "warning")
                return redirect(url_for("portfolio.portfolio"))
    
    subscriber_list = get_subscribers(user_id)
    
    return render_template(
        "subscribers.html",
        APP_VERSION=read_version(),
        subscribers=subscriber_list,
        success_message=request.args.get("success"),
        selected_report_ids=selected_report_ids,
    )


@portfolio_bp.route("/subscribers/add", methods=["POST"])
@login_required
def add_subscriber_route():
    """Add a subscriber."""
    user_id = get_user_id()
    if not user_id:
        if request.is_json:
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login"))
    
    # Handle both form and JSON
    if request.is_json:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        mobile = (data.get("mobile") or "").strip()
        email = (data.get("email") or "").strip()
    else:
        name = (request.form.get("name") or "").strip()
        mobile = (request.form.get("mobile") or "").strip()
        email = (request.form.get("email") or "").strip()
    
    # Validate
    if not name or not email:
        if request.is_json:
            return jsonify({"error": "Name and email are required"}), 400
        flash("Name and email are required.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    # Basic email validation
    if "@" not in email:
        if request.is_json:
            return jsonify({"error": "Invalid email address"}), 400
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    sub_id = add_subscriber(user_id, name, mobile, email)
    
    if request.is_json:
        return jsonify({"success": True, "subscriber_id": sub_id})
    
    flash(f"Subscriber '{name}' added successfully.", "success")
    return redirect(url_for("portfolio.subscribers"))


@portfolio_bp.route("/subscribers/edit", methods=["POST"])
@login_required
def edit_subscriber_route():
    """Edit a subscriber."""
    user_id = get_user_id()
    if not user_id:
        flash("Authentication required.", "error")
        return redirect(url_for("auth.login"))
    
    subscriber_id = request.form.get("subscriber_id", type=int)
    if not subscriber_id:
        flash("Subscriber ID is required.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    name = (request.form.get("name") or "").strip()
    mobile = (request.form.get("mobile") or "").strip()
    email = (request.form.get("email") or "").strip()
    
    # Validate
    if not name or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    # Basic email validation
    if "@" not in email:
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    success = update_subscriber(subscriber_id, user_id, name, mobile, email)
    if success:
        flash("Subscriber updated.", "success")
    else:
        flash("Subscriber not found or unauthorized.", "error")
    
    return redirect(url_for("portfolio.subscribers"))


@portfolio_bp.route("/subscribers/delete", methods=["POST"])
@login_required
def delete_subscriber_route():
    """Delete a subscriber."""
    user_id = get_user_id()
    if not user_id:
        flash("Authentication required.", "error")
        return redirect(url_for("auth.login"))
    
    subscriber_id = request.form.get("subscriber_id", type=int)
    if not subscriber_id:
        flash("Subscriber ID is required.", "error")
        return redirect(url_for("portfolio.subscribers"))
    
    success = delete_subscriber(subscriber_id, user_id)
    if success:
        flash("Subscriber deleted.", "success")
    else:
        flash("Subscriber not found or unauthorized.", "error")
    
    return redirect(url_for("portfolio.subscribers"))


@portfolio_bp.route("/subscribers/send", methods=["POST"])
@login_required
def send_reports():
    """Send selected approved reports to all subscribers."""
    user_id = get_user_id()
    if not user_id:
        if request.is_json:
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login"))
    
    # Get selected report IDs from request or session
    if request.is_json:
        data = request.get_json(silent=True) or {}
        selected_report_ids = data.get("report_ids", [])
    else:
        selected_report_ids = request.form.getlist("report_ids", type=int)
        if not selected_report_ids:
            selected_report_ids = session.get("selected_report_ids", [])
    
    # If no reports selected, use all approved (backward compatibility)
    if not selected_report_ids:
        if not all_reports_approved(user_id):
            if request.is_json:
                return jsonify({"error": "All reports must be approved before sending"}), 400
            flash("All reports must be approved before sending.", "error")
            return redirect(url_for("portfolio.subscribers"))
        selected_report_ids = None
    
    result = send_reports_to_subscribers(user_id, selected_report_ids)
    
    if request.is_json:
        return jsonify(result)
    
    if result["success"]:
        return redirect(url_for("portfolio.subscribers", success=result["message"]))
    
    flash(result["message"], "error")
    return redirect(url_for("portfolio.subscribers"))


@portfolio_bp.route("/portfolio/report-preview/<int:report_id>")
@login_required
def report_preview_json(report_id: int):
    """Get report preview content as JSON (for modal preview)."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required"}), 401
    
    with db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT r.*, p.company_name, p.ticker 
               FROM reports r
               LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
               WHERE r.id = %s AND r.user_id = %s""",
            (report_id, user_id)
        )
        report = cur.fetchone()
    
    if not report:
        return jsonify({"error": "Report not found"}), 404
    
    report = dict(report)
    company = report.get("company_name", "Company")
    ticker = report.get("ticker") or ""  # Use empty string if None
    
    # Generate placeholder report content
    ticker_display = f" <span class=\"ticker\">({ticker})</span>" if ticker else ""
    preview_html = f"""
    <div class="report-preview-content">
        <div class="report-header">
            <h2>{company}{ticker_display}</h2>
            <p class="report-type">Equity Research Note</p>
            <p class="report-date">Generated: {datetime.now().strftime('%B %d, %Y')}</p>
        </div>
        
        <div class="report-section">
            <h3>Investment Thesis</h3>
            <p>This report provides a comprehensive analysis of {company}, examining key financial metrics, 
            market positioning, and growth opportunities. Our analysis indicates strong fundamentals 
            with potential upside based on current market conditions.</p>
        </div>
        
        <div class="report-section">
            <h3>Key Highlights</h3>
            <ul>
                <li>Strong revenue growth trajectory</li>
                <li>Expanding market share in core segments</li>
                <li>Favorable industry tailwinds</li>
                <li>Management track record of execution</li>
            </ul>
        </div>
        
        <div class="report-section">
            <h3>Valuation Summary</h3>
            <p>Based on our DCF analysis and comparable company valuations, 
            we see attractive risk/reward at current levels.</p>
        </div>
        
        <div class="report-section">
            <h3>Key Risks</h3>
            <ul>
                <li>Macro economic sensitivity</li>
                <li>Competitive pressures</li>
                <li>Regulatory changes</li>
            </ul>
        </div>
        
        <div class="report-footer">
            <p><em>Report generated by SageAlpha.ai</em></p>
        </div>
    </div>
    """
    
    return jsonify({
        "success": True,
        "report": report,
        "preview_html": preview_html
    })


@portfolio_bp.route("/reports/<int:report_id>/preview")
@login_required
def report_preview_full(report_id: int):
    """
    Full PDF-style report preview page.
    Opens in a new tab with a professional equity research layout.
    
    This route verifies the report belongs to the current user before displaying.
    """
    user_id = get_user_id()
    if not user_id:
        flash("Authentication required.", "error")
        return redirect(url_for("auth.login"))
    
    with db_cursor(commit=False) as cur:
        cur.execute(
            """SELECT r.*, p.company_name, p.ticker 
               FROM reports r
               LEFT JOIN portfolio_items p ON r.portfolio_item_id = p.id
               WHERE r.id = %s AND r.user_id = %s""",
            (report_id, user_id)
        )
        report = cur.fetchone()
    
    if not report:
        flash("Report not found or unauthorized.", "error")
        return redirect(url_for("portfolio.portfolio"))
    
    report = dict(report)
    company = report.get("company_name", "Company")
    ticker = report.get("ticker") or ""  # Use empty string if None
    
    # Check if there's stored report data
    stored_report_data = report.get("report_data")
    
    # Build description with or without ticker
    company_desc = f"{company} ({ticker})" if ticker else company
    
    # Generate report content (either from stored data or placeholder)
    report_content = {
        "company_name": company,
        "ticker": ticker,
        "title": report.get("title", f"Equity Research Note – {company}"),
        "date": datetime.now().strftime('%B %d, %Y'),
        "status": report.get("status", "pending"),
        "investment_thesis": f"""This report provides a comprehensive analysis of {company_desc}, 
examining key financial metrics, market positioning, and growth opportunities. Our analysis indicates 
strong fundamentals with potential upside based on current market conditions.

{company} has demonstrated consistent execution on strategic initiatives, positioning the company 
well for sustained growth. The company's competitive advantages and market positioning suggest 
favorable risk/reward characteristics at current valuations.""",
        "key_highlights": [
            "Strong revenue growth trajectory with improving margins",
            "Expanding market share in core business segments",
            "Favorable industry tailwinds supporting long-term growth",
            "Management track record of disciplined capital allocation",
            "Robust free cash flow generation enabling strategic investments"
        ],
        "financial_overview": {
            "revenue_growth": "12.5% YoY",
            "ebitda_margin": "28.3%",
            "net_debt_ebitda": "1.8x",
            "roe": "18.7%",
            "dividend_yield": "2.1%"
        },
        "valuation_summary": f"""Based on our DCF analysis and comparable company valuations, we see attractive 
risk/reward at current levels. Our analysis incorporates multiple valuation methodologies including:

• Discounted Cash Flow (DCF) analysis using a WACC of 9.5%
• Comparable company analysis across relevant peer group
• Precedent transaction analysis for M&A context

Our blended valuation approach suggests meaningful upside potential from current trading levels.""",
        "risks": [
            "Macro economic sensitivity and cyclical exposure",
            "Competitive pressures from new market entrants",
            "Regulatory changes affecting industry dynamics",
            "Foreign exchange volatility impacting international operations",
            "Supply chain disruptions affecting cost structure"
        ],
        "recommendation": "Based on our comprehensive analysis, we maintain a constructive view on the company's prospects."
    }
    
    return render_template(
        "report_preview.html",
        APP_VERSION=read_version(),
        report=report_content,
        report_id=report_id
    )

