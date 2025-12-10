"""
SageAlpha.ai Authentication Blueprint
Modern Flask 3.x authentication with bcrypt password hashing
"""

from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from authlib.integrations.flask_client import OAuth
import os

from db_sqlite import (
    User,
    create_user,
    get_user_by_username,
    get_user_by_email,
    user_exists,
    get_user_preferences,
    update_user_preferences,
)

auth_bp = Blueprint("auth", __name__, template_folder="../templates")

# OAuth setup - will be initialized by the app factory
oauth = OAuth()
google = None


def init_oauth(app):
    """Initialize OAuth providers. Called from app factory."""
    global google
    oauth.init_app(app)

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if client_id and client_secret:
        google = oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        print("[OAuth] ✓ Google OAuth configured")
    else:
        google = None
        print("[OAuth] ⚠ Google OAuth not configured (missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET)")


def read_version():
    """Get application version from env or VERSION file."""
    import os

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


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Render login page (GET), accept form POST (username/password).
    Accepts demo accounts demouser/devuser/produser for testing.
    """
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        return redirect("/")

    if request.method == "GET":
        return render_template("login.html", APP_VERSION=read_version())

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not username or not password:
        return (
            render_template(
                "login.html",
                error="Username and password required.",
                username=username,
                APP_VERSION=read_version(),
            ),
            400,
        )

    user = None
    try:
        user = get_user_by_username(username)
    except Exception as e:
        current_app.logger.error(f"[login] DB lookup failed: {e!r}")

    authenticated = False
    if user:
        if hasattr(user, "check_password") and callable(user.check_password):
            try:
                authenticated = user.check_password(password)
            except Exception:
                authenticated = False
        else:
            if getattr(user, "password", None) == password:
                authenticated = True

    # Demo accounts fallback
    demo_passwords = {
        "demouser": "Demouser",
        "devuser": "Devuser",
        "produser": "Produser",
    }
    if not authenticated and username in demo_passwords:
        if password == demo_passwords[username]:
            authenticated = True
            if not user:

                class _TempUser:
                    def __init__(self, username):
                        self.id = username
                        self.username = username
                        self.is_active = True
                        self.is_authenticated = True
                        self.is_anonymous = False

                    def get_id(self):
                        return str(self.id)

                user = _TempUser(username)

    if not authenticated:
        return (
            render_template(
                "login.html",
                error="Invalid username or password.",
                username=username,
                APP_VERSION=read_version(),
            ),
            401,
        )

    try:
        login_user(user)
    except Exception as e:
        current_app.logger.warning(f"[login] login_user failed: {e!r}")
        session["logged_in"] = True
        session["username"] = username

    return redirect("/")


@auth_bp.route("/register", methods=["POST"])
def register():
    """Handle new user registration from the sign-up form."""
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
        return redirect("/")

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    register_error = None
    if not username or not email or not password:
        register_error = "All fields are required."
    elif len(password) < 8:
        register_error = "Password must be at least 8 characters long."
    elif "@" not in email:
        register_error = "Please enter a valid email address."

    if register_error is None:
        try:
            if user_exists(username):
                register_error = "Username already taken. Please choose another."
            elif get_user_by_email(email):
                register_error = "Email address is already registered."
        except Exception as e:
            current_app.logger.error(f"[register] DB lookup failed: {e!r}")
            register_error = "Unexpected error. Please try again."

    if register_error:
        return (
            render_template(
                "login.html",
                show_register=True,
                register_error=register_error,
                reg_username=username,
                reg_email=email,
                APP_VERSION=read_version(),
            ),
            400,
        )

    try:
        user = create_user(
            username=username,
            password=password,
            email=email,
        )
        if not user:
            raise Exception("User creation returned None")
    except Exception as e:
        current_app.logger.error(f"[register] Failed to create user: {e!r}")
        return (
            render_template(
                "login.html",
                show_register=True,
                register_error="Could not create account. Please try again.",
                reg_username=username,
                reg_email=email,
                APP_VERSION=read_version(),
            ),
            500,
        )

    try:
        login_user(user)
    except Exception as e:
        current_app.logger.warning(f"[register] login_user failed: {e!r}")
        session["logged_in"] = True
        session["username"] = username

    return redirect("/")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Clear Flask-Login state and session, redirect to login."""
    try:
        logout_user()
    except Exception:
        pass

    session.clear()

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "next": url_for("auth.login")})

    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """User profile page."""
    user_id = current_user.id if hasattr(current_user, "id") else None
    if not user_id:
        flash("Authentication required.", "error")
        return redirect(url_for("auth.login"))
    
    if request.method == "POST":
        # Handle form submission
        communication_style = request.form.get("communication_style", "")
        language = request.form.get("language", "en")
        plan = request.form.get("plan", "free")
        preferred_model = request.form.get("preferred_model", "sagealpha_v3")
        # Validate model selection
        if preferred_model not in ["sagealpha_v3", "sagealpha_v4"]:
            preferred_model = "sagealpha_v3"
        preference_mode = request.form.get("preference_mode", "accuracy")
        
        # Parse communication style checkboxes
        styles = []
        if request.form.get("style_formal"):
            styles.append("formal")
        if request.form.get("style_friendly"):
            styles.append("friendly")
        if request.form.get("style_concise"):
            styles.append("concise")
        if request.form.get("style_detailed"):
            styles.append("detailed")
        communication_style = ",".join(styles) if styles else ""
        
        success = update_user_preferences(
            user_id=user_id,
            communication_style=communication_style,
            language=language,
            plan=plan,
            preferred_model=preferred_model,
            preference_mode=preference_mode
        )
        
        if success:
            flash("Profile updated successfully.", "success")
        else:
            flash("Failed to update profile.", "error")
        
        return redirect(url_for("auth.profile"))
    
    # GET request - load preferences
    preferences = get_user_preferences(user_id)
    
    # Parse communication styles
    styles_list = preferences.get("communication_style", "").split(",") if preferences.get("communication_style") else []
    
    return render_template(
        "profile.html",
        APP_VERSION=read_version(),
        preferences=preferences,
        styles_list=styles_list,
        current_user=current_user
    )


@auth_bp.route("/user", methods=["GET"])
def user():
    """Return current user info as JSON."""
    if not (
        hasattr(current_user, "is_authenticated") and current_user.is_authenticated
    ):
        return jsonify(
            {"username": "Guest", "email": "guest@gmail.com", "avatar_url": None}
        )

    return jsonify(
        {
            "username": current_user.username,
            "email": f"{current_user.username}@local",
            "avatar_url": None,
        }
    )


@auth_bp.route("/auth/google")
def google_login():
    """Initiate Google OAuth login."""
    if current_user.is_authenticated:
        return redirect(url_for("portfolio.portfolio"))

    if not google:
        flash("Google OAuth is not configured.", "error")
        return redirect(url_for("auth.login"))

    redirect_uri = url_for("auth.google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    if not google:
        flash("Google OAuth is not configured.", "error")
        return redirect(url_for("auth.login"))

    try:
        token = google.authorize_access_token()
        userinfo = google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
    except Exception as e:
        flash("Google authentication failed.", "error")
        return redirect(url_for("auth.login"))

    # Extract user information
    google_id = userinfo.get("id")
    email = userinfo.get("email")
    name = userinfo.get("name", email.split("@")[0] if email else "User")

    if not email:
        flash("Email address is required for login.", "error")
        return redirect(url_for("auth.login"))

    # Check if user exists by email
    existing_user = get_user_by_email(email)

    if existing_user:
        # User exists, log them in
        login_user(existing_user)
        flash(f"Welcome back, {existing_user.display_name or existing_user.username}!", "success")
    else:
        # Create new user
        username = email.split("@")[0] + "_" + str(google_id)[:8]  # Make unique username
        display_name = name

        # Ensure username is unique
        base_username = username
        counter = 1
        while user_exists(username):
            username = f"{base_username}_{counter}"
            counter += 1

        # Create user with a random password (they won't use it)
        import secrets
        random_password = secrets.token_urlsafe(32)

        try:
            new_user = create_user(
                username=username,
                password=random_password,
                display_name=display_name,
                email=email
            )
            login_user(new_user)
            flash(f"Welcome to SageAlpha, {display_name}!", "success")
        except Exception as e:
            flash("Failed to create account. Please try again.", "error")
            return redirect(url_for("auth.login"))

    return redirect(url_for("portfolio.portfolio"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Handle forgot password requests."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()

        if not email:
            flash("Please enter an email address.", "error")
            return redirect(url_for("auth.forgot_password"))

        # Check if user exists
        user = get_user_by_email(email)
        if user:
            # Generate a reset token (UUID for now)
            import uuid
            reset_token = str(uuid.uuid4())

            # In a real implementation, you'd:
            # 1. Store the token with an expiration time in the database
            # 2. Send an email with the reset link

            # For now, just log it (in production, this would be emailed)
            reset_url = url_for("auth.reset_password", token=reset_token, _external=True)
            print(f"[FORGOT PASSWORD] Reset link for {email}: {reset_url}")

            flash("If this email is registered, a reset link has been sent.", "info")
        else:
            # Always show the same message to prevent email enumeration
            flash("If this email is registered, a reset link has been sent.", "info")

        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", APP_VERSION=read_version())


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Handle password reset with token."""
    # In a real implementation, you'd validate the token from the database
    # and check if it hasn't expired

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password or len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for("auth.reset_password", token=token))

        # In a real implementation, you'd:
        # 1. Find the user associated with the token
        # 2. Update their password
        # 3. Mark the token as used

        flash("Password has been reset successfully. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", APP_VERSION=read_version(), token=token)

