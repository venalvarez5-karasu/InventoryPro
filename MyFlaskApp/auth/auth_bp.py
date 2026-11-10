import hashlib
import hmac
import json
import re
import secrets
import time
from functools import lru_cache, wraps
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_mail import Message
from MySQLdb.cursors import DictCursor
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

from MyFlaskApp import limiter, mail, mysql


auth_bp = Blueprint(
    "auth",
    __name__,
    template_folder="templates",
    static_folder="static",
)

# VALIDATION RULES

EMAIL_RE = re.compile(
    r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
)

PHONE_RE = re.compile(
    r"^09[0-9]{9}$"
)

NAME_RE = re.compile(
    r"^[^\W\d_]+(?: [^\W\d_]+)*$",
    re.UNICODE,
)

POSTAL_RE = re.compile(
    r"^[0-9]{4}$"
)


def valid_name(value, max_length=80):
    return bool(
        2 <= len(value) <= max_length
        and NAME_RE.fullmatch(value)
    )


def valid_address_text(
    value,
    max_length,
    min_length=2
):
    return (
        min_length <= len(value) <= max_length
        and all(
            c.isprintable() and c not in "<>"
            for c in value
        )
    )


def good_password(password):
    # 8 characters, at least 1 symbol
    # and at least 1 number
    return (
        8 <= len(password) <= 128
        and any(
            "0" <= c <= "9"
            for c in password
        )
        and any(
            not c.isalnum()
            and not c.isspace()
            for c in password
        )
    )

# DATABASE HELPERS

def find_one(sql, values=()):
    cur = mysql.connection.cursor(DictCursor)

    try:
        cur.execute(sql, values)
        return cur.fetchone()
    finally:
        cur.close()


def save(sql, values=()):
    cur = mysql.connection.cursor()

    try:
        cur.execute(sql, values)
        mysql.connection.commit()
        return cur.lastrowid

    except Exception:
        mysql.connection.rollback()
        raise

    finally:
        cur.close()

# LOGIN AND ROLE PROTECTION

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    user = find_one(
        """
        SELECT
            id,
            first_name,
            last_name,
            email,
            mobile_number,
            role,
            account_status
        FROM users
        WHERE id = %s
        """,
        (user_id,),
    )

    if user and user["account_status"] == "active":
        return user

    return None


def login_required(view):

    @wraps(view)
    def protected(*args, **kwargs):

        if not current_user():
            flash(
                "Please log in first.",
                "warning"
            )
            return redirect(
                url_for("auth.login")
            )

        return view(*args, **kwargs)

    return protected


def role_required(*roles):

    def decorator(view):

        @wraps(view)
        def protected(*args, **kwargs):

            user = current_user()

            if not user:
                return redirect(
                    url_for("auth.login")
                )

            if user["role"] not in roles:
                abort(403)

            return view(*args, **kwargs)

        return protected

    return decorator

# EMAIL OTP HELPERS

def is_email_verified(user_id):
    return bool(
        find_one(
            """
            SELECT id
            FROM verification_codes
            WHERE user_id = %s
              AND purpose = 'registration'
              AND channel = 'email'
              AND used_at IS NOT NULL
            LIMIT 1
            """,
            (user_id,),
        )
    )


def otp_hash(user_id, purpose, code):

    value = (
        f"{user_id}:{purpose}:{code}"
    ).encode("utf-8")

    secret = current_app.secret_key.encode(
        "utf-8"
    )

    return hmac.new(
        secret,
        value,
        hashlib.sha256,
    ).hexdigest()


def send_code(user, purpose):

    sender = current_app.config.get(
        "MAIL_USERNAME"
    )

    password = current_app.config.get(
        "MAIL_PASSWORD"
    )

    if (
        not sender
        or not password
        or current_app.config.get("MAIL_SUPPRESS_SEND")
    ):
        return (
            False,
            "Email sending is not configured."
        )

    # Check resend cooldown
    last = find_one(
        """
        SELECT
            TIMESTAMPDIFF(
                SECOND,
                created_at,
                NOW()
            ) AS seconds_ago
        FROM verification_codes
        WHERE user_id = %s
          AND channel = 'email'
          AND purpose = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (user["id"], purpose),
    )

    if (
        last
        and last["seconds_ago"] is not None
        and last["seconds_ago"] < 60
    ):
        return (
            False,
            "Please wait one minute before "
            "requesting another code."
        )

    # Generate secure 6-digit OTP
    code = f"{secrets.randbelow(1000000):06d}"

    record_id = save(
        """
        INSERT INTO verification_codes
        (
            user_id,
            channel,
            purpose,
            code_hash,
            expires_at
        )
        VALUES
        (
            %s,
            'email',
            %s,
            %s,
            DATE_ADD(
                NOW(),
                INTERVAL 10 MINUTE
            )
        )
        """,
        (
            user["id"],
            purpose,
            otp_hash(
                user["id"],
                purpose,
                code
            ),
        ),
    )

    # Compose OTP email
    message = Message(
        subject=(
            "Tali's Bread & Pastries "
            "- Verification Code"
        ),
        sender=sender,
        recipients=[user["email"]],
        body=(
            f"Your verification code is: {code}\n\n"
            "It expires in 10 minutes.\n"
            "If you did not request it, "
            "ignore this message."
        ),
    )

    try:
        mail.send(message)

    except Exception:
        current_app.logger.exception(
            "OTP EMAIL SENDING FAILED"
        )

        save(
            """
            DELETE FROM verification_codes
            WHERE id = %s
            """,
            (record_id,),
        )

        return (
            False,
            "Unable to send the verification email."
        )

    return (
        True,
        "A 6-digit verification code "
        "has been sent to your email."
    )

# CUSTOMER REGISTRATION

@auth_bp.route(
    "/register",
    methods=["GET", "POST"]
)
@limiter.limit(
    "5 per hour",
    methods=["POST"]
)
def register():

    if request.method == "POST":

        first = request.form.get(
            "first_name", ""
        ).strip()

        last = request.form.get(
            "last_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        mobile = request.form.get(
            "mobile_number", ""
        ).strip()

        password = request.form.get(
            "password", ""
        )

        confirm = request.form.get(
            "confirm_password", ""
        )

        # Validate names
        if (
            not valid_name(first)
            or not valid_name(last)
        ):
            flash(
                "Names must contain letters "
                "and spaces only (2-80 characters).",
                "danger"
            )

        # Validate email
        elif (
            len(email) > 190
            or not EMAIL_RE.fullmatch(email)
        ):
            flash(
                "Enter a valid email address.",
                "danger"
            )

        # Validate Philippine mobile number
        elif not PHONE_RE.fullmatch(mobile):
            flash(
                "Enter exactly 11 digits "
                "starting with 09.",
                "danger"
            )

        # Validate password
        elif not good_password(password):
            flash(
                "Password needs 8-128 characters, "
                "a symbol, and a number.",
                "danger"
            )

        # Confirm password
        elif password != confirm:
            flash(
                "Passwords do not match.",
                "danger"
            )

        # Terms and conditions
        elif request.form.get("terms") != "yes":
            flash(
                "Please accept the terms "
                "and privacy policy.",
                "danger"
            )

        # Check duplicate email
        elif find_one(
            """
            SELECT id
            FROM users
            WHERE LOWER(email) = %s
            LIMIT 1
            """,
            (email,),
        ):
            flash(
                "This email is already registered. "
                "Please log in.",
                "danger"
            )

        # Check duplicate mobile number
        elif find_one(
            """
            SELECT id
            FROM users
            WHERE mobile_number = %s
            LIMIT 1
            """,
            (mobile,),
        ):
            flash(
                "This mobile number "
                "is already registered.",
                "danger"
            )

        # Check mail configuration
        elif (
            not current_app.config.get("MAIL_USERNAME")
            or not current_app.config.get("MAIL_PASSWORD")
        ):
            flash(
                "Email verification "
                "is not configured.",
                "danger"
            )

        else:
            try:
                user_id = save(
                    """
                    INSERT INTO users
                    (
                        first_name,
                        last_name,
                        email,
                        mobile_number,
                        password_hash,
                        role
                    )
                    VALUES
                    (
                        %s, %s, %s,
                        %s, %s, 'customer'
                    )
                    """,
                    (
                        first,
                        last,
                        email,
                        mobile,
                        generate_password_hash(
                            password
                        ),
                    ),
                )

                session["otp_user_id"] = user_id
                session["otp_purpose"] = (
                    "registration"
                )

                sent, message = send_code(
                    {
                        "id": user_id,
                        "email": email,
                    },
                    "registration",
                )

                flash(
                    message,
                    "success" if sent else "warning"
                )

                return redirect(
                    url_for("auth.otp")
                )

            except Exception:
                current_app.logger.exception(
                    "Registration failed"
                )

                flash(
                    "Unable to register. "
                    "Please try again.",
                    "danger"
                )

        return render_template(
            "register.html",
            title="Register",
        ), 400

    return render_template(
        "register.html",
        title="Register",
    )

# REAL-TIME EMAIL / NUMBER CHECK

@auth_bp.route(
    "/check-availability",
    methods=["POST"]
)
@limiter.limit("30 per minute")
def check_availability():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {
            "valid": False,
            "exists": False
        }, 400

    field = data.get("field")

    value = str(
        data.get("value", "")
    ).strip()

    if field == "email":

        value = value.lower()

        if (
            len(value) > 190
            or not EMAIL_RE.fullmatch(value)
        ):
            return {
                "valid": False,
                "exists": False
            }, 400

        existing = find_one(
            """
            SELECT id
            FROM users
            WHERE LOWER(email) = %s
            LIMIT 1
            """,
            (value,),
        )

    elif field == "mobile_number":

        if not PHONE_RE.fullmatch(value):
            return {
                "valid": False,
                "exists": False
            }, 400

        existing = find_one(
            """
            SELECT id
            FROM users
            WHERE mobile_number = %s
            LIMIT 1
            """,
            (value,),
        )

    else:
        return {
            "valid": False,
            "exists": False
        }, 400

    return {
        "valid": True,
        "exists": bool(existing)
    }

# LOGIN

@auth_bp.route(
    "/login",
    methods=["GET", "POST"]
)
@limiter.limit(
    "5 per minute",
    methods=["POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        user = (
            find_one(
                """
                SELECT
                    id,
                    first_name,
                    email,
                    role,
                    account_status,
                    password_hash
                FROM users
                WHERE LOWER(email) = %s
                """,
                (email,),
            )
            if email
            else None
        )

        if (
            not user
            or not user["password_hash"]
            or not check_password_hash(
                user["password_hash"],
                password
            )
        ):
            flash(
                "Invalid email or password.",
                "danger"
            )

        elif user["account_status"] != "active":
            flash(
                "This account is disabled.",
                "danger"
            )

        elif (
            user["role"] == "customer"
            and not is_email_verified(user["id"])
        ):
            session["otp_user_id"] = user["id"]
            session["otp_purpose"] = (
                "registration"
            )

            flash(
                "Please verify your email first. "
                "Resend a code if needed.",
                "warning"
            )

            return redirect(
                url_for("auth.otp")
            )

        else:
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True

            flash(
                "Welcome back!",
                "success"
            )

            if user["role"] in ("admin", "staff"):
                destination = "/admin/"
            else:
                destination = "/"

            next_page = request.form.get(
                "next", ""
            ).strip()

            if (
                user["role"] == "customer"
                and next_page.startswith("/")
                and not next_page.startswith("//")
                and "\\" not in next_page
                and not next_page.startswith("/admin")
            ):
                destination = next_page

            return redirect(destination)

        return render_template(
            "login.html",
            title="Login",
        ), 401

    return render_template(
        "login.html",
        title="Login",
    )

# VERIFY EMAIL OTP

@auth_bp.route(
    "/otp",
    methods=["GET", "POST"]
)
@limiter.limit(
    "8 per minute",
    methods=["POST"]
)
def otp():

    user_id = session.get(
        "otp_user_id"
    )

    purpose = session.get(
        "otp_purpose"
    )

    if (
        not user_id
        or purpose not in (
            "registration",
            "password_reset",
        )
    ):
        return redirect(
            url_for("auth.login")
        )

    if request.method == "POST":

        code = request.form.get(
            "otp", ""
        ).strip()

        record = find_one(
            """
            SELECT
                id,
                code_hash,
                failed_attempts,
                used_at,
                (expires_at > NOW()) AS valid_time
            FROM verification_codes
            WHERE user_id = %s
              AND purpose = %s
              AND channel = 'email'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, purpose),
        )

        if not re.fullmatch(
            r"[0-9]{6}",
            code
        ):
            flash(
                "Enter a six-digit code.",
                "danger"
            )

        elif (
            not record
            or record["used_at"]
            or not record["valid_time"]
        ):
            flash(
                "Code expired or invalid. "
                "Request another code.",
                "danger"
            )

        elif record["failed_attempts"] >= 5:
            flash(
                "Too many attempts. "
                "Request another code.",
                "danger"
            )

        elif not hmac.compare_digest(
            record["code_hash"],
            otp_hash(
                user_id,
                purpose,
                code
            ),
        ):
            save(
                """
                UPDATE verification_codes
                SET failed_attempts =
                    failed_attempts + 1
                WHERE id = %s
                """,
                (record["id"],),
            )

            flash(
                "Incorrect code.",
                "danger"
            )

        else:
            save(
                """
                UPDATE verification_codes
                SET used_at = NOW()
                WHERE id = %s
                  AND used_at IS NULL
                """,
                (record["id"],),
            )

            session.pop(
                "otp_user_id",
                None
            )

            session.pop(
                "otp_purpose",
                None
            )

            # Password reset OTP
            if purpose == "password_reset":

                session["reset_user_id"] = (
                    user_id
                )

                session["reset_until"] = (
                    time.time() + 600
                )

                return redirect(
                    url_for(
                        "auth.reset_password"
                    )
                )

            # Registration OTP
            # Automatically log in customer
            user = find_one(
                """
                SELECT
                    id,
                    role,
                    account_status
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )

            if (
                not user
                or user["role"] != "customer"
                or user["account_status"] != "active"
            ):
                flash(
                    "Unable to complete registration. "
                    "Please contact support.",
                    "danger"
                )

                return redirect(
                    url_for("auth.login")
                )

            session.clear()

            session["user_id"] = user["id"]
            session.permanent = True

            flash(
                "Email verified! Please complete "
                "your delivery profile.",
                "success"
            )

            return redirect(
                url_for(
                    "auth.complete_profile"
                )
            )

    return render_template(
        "otp.html",
        title="Email Verification",
    )

# RESEND OTP

@auth_bp.route(
    "/resend-otp",
    methods=["POST"]
)
@limiter.limit("3 per minute")
def resend_otp():

    user_id = session.get(
        "otp_user_id"
    )

    purpose = session.get(
        "otp_purpose"
    )

    if (
        user_id
        and purpose in (
            "registration",
            "password_reset",
        )
    ):
        user = find_one(
            """
            SELECT id, email
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )

        if user:
            sent, message = send_code(
                user,
                purpose
            )

            flash(
                message,
                "success" if sent else "warning"
            )

    return redirect(
        url_for("auth.otp")
    )

# FORGOT PASSWORD

@auth_bp.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
@limiter.limit(
    "5 per hour",
    methods=["POST"]
)
def forgot_password():

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        user = (
            find_one(
                """
                SELECT id, email
                FROM users
                WHERE LOWER(email) = %s
                """,
                (email,),
            )
            if EMAIL_RE.fullmatch(email)
            else None
        )

        if (
            user
            and is_email_verified(user["id"])
        ):
            session["otp_user_id"] = (
                user["id"]
            )

            session["otp_purpose"] = (
                "password_reset"
            )

            send_code(
                user,
                "password_reset"
            )

        else:
            session.pop(
                "otp_user_id",
                None
            )

            session.pop(
                "otp_purpose",
                None
            )

        flash(
            "If the account exists, "
            "a password reset code has been sent.",
            "success"
        )

        if (
            user
            and is_email_verified(user["id"])
        ):
            return redirect(
                url_for("auth.otp")
            )

        return redirect(
            url_for("auth.forgot_password")
        )

    return render_template(
        "forgot_password.html",
        title="Forgot Password",
    )

# RESET PASSWORD

@auth_bp.route(
    "/reset-password",
    methods=["GET", "POST"]
)
@limiter.limit(
    "5 per hour",
    methods=["POST"]
)
def reset_password():

    user_id = session.get(
        "reset_user_id"
    )

    if (
        not user_id
        or time.time() > session.get(
            "reset_until", 0
        )
    ):
        session.pop(
            "reset_user_id",
            None
        )

        session.pop(
            "reset_until",
            None
        )

        return redirect(
            url_for(
                "auth.forgot_password"
            )
        )

    if request.method == "POST":

        password = request.form.get(
            "password", ""
        )

        confirm = request.form.get(
            "confirm_password", ""
        )

        if not good_password(password):
            flash(
                "Use 8-128 characters, "
                "a symbol, and a number.",
                "danger"
            )

        elif password != confirm:
            flash(
                "Passwords do not match.",
                "danger"
            )

        else:
            save(
                """
                UPDATE users
                SET password_hash = %s
                WHERE id = %s
                """,
                (
                    generate_password_hash(
                        password
                    ),
                    user_id,
                ),
            )

            session.clear()

            flash(
                "Password changed! "
                "Please log in.",
                "success"
            )

            return redirect(
                url_for("auth.login")
            )

    return render_template(
        "reset_password.html",
        title="Reset Password",
    )

# PHILIPPINE ADDRESS DROPDOWNS

PSGC_API = "https://psgc.cloud/api/v2"

PROVINCE_ENDPOINTS = {
    "Laguna": (
        "/provinces/Laguna/"
        "cities-municipalities"
    ),
    "Cavite": (
        "/provinces/Cavite/"
        "cities-municipalities"
    ),
    "Metro Manila (NCR)": (
        "/regions/1300000000/"
        "cities-municipalities"
    ),
}

# FETCH PHILIPPINE LOCATIONS

@lru_cache(maxsize=512)
def fetch_psgc(path):

    req = Request(
        PSGC_API + path,
        headers={
            "Accept": "application/json",
            "User-Agent": "InventoryPro/1.0",
        },
    )

    with urlopen(
        req,
        timeout=12
    ) as response:
        data = json.load(response)

    if isinstance(data, dict):
        data = data.get(
            "data",
            data.get("items")
        )

    if not isinstance(data, list):
        raise ValueError(
            "Unexpected location API response"
        )

    items = []

    for item in data:

        if isinstance(item, dict):

            code = str(
                item.get("code", "")
            ).strip()

            name = str(
                item.get("name", "")
            ).strip()

            if code and name:
                items.append({
                    "code": code,
                    "name": name,
                })

    return sorted(
        items,
        key=lambda item: item["name"].casefold(),
    )

# GET CITIES / MUNICIPALITIES

def get_cities(province):

    path = PROVINCE_ENDPOINTS.get(
        province
    )

    return (
        fetch_psgc(path)
        if path
        else []
    )

# GET BARANGAYS

def get_barangays(
    province,
    city_code
):
    cities = get_cities(province)

    valid_city = any(
        city["code"] == city_code
        for city in cities
    )

    if not valid_city:
        return []

    return fetch_psgc(
        "/cities-municipalities/"
        + quote(city_code, safe="")
        + "/barangays"
    )

# SERVER-SIDE ADDRESS VALIDATION

def valid_selected_address(
    province,
    city_name,
    barangay_name
):
    try:
        selected_city = next(
            (
                item
                for item in get_cities(province)
                if item["name"].casefold()
                == city_name.casefold()
            ),
            None,
        )

        if not selected_city:
            return False

        barangays = get_barangays(
            province,
            selected_city["code"],
        )

        return any(
            item["name"].casefold()
            == barangay_name.casefold()
            for item in barangays
        )

    except Exception:
        current_app.logger.exception(
            "Unable to validate Philippine address"
        )

        return False

# ADDRESS OPTIONS API

@auth_bp.route(
    "/address-options",
    methods=["GET"]
)
@login_required
@limiter.limit("60 per minute")
def address_options():

    province = request.args.get(
        "province", ""
    ).strip()

    level = request.args.get(
        "level", ""
    ).strip()

    city_code = request.args.get(
        "city_code", ""
    ).strip()

    if province not in PROVINCE_ENDPOINTS:
        return {"items": []}, 400

    try:
        if level == "city":
            items = get_cities(
                province
            )

        elif level == "barangay":
            items = get_barangays(
                province,
                city_code
            )

        else:
            return {"items": []}, 400

        return {
            "items": items
        }

    except Exception:
        current_app.logger.exception(
            "Unable to load Philippine locations"
        )

        return {
            "items": [],
            "error": "Location service unavailable",
        }, 503

# COMPLETE CUSTOMER PROFILE

@auth_bp.route(
    "/complete-profile",
    methods=["GET", "POST"]
)
@login_required
def complete_profile():

    user = current_user()

    address = find_one(
        """
        SELECT *
        FROM customer_addresses
        WHERE user_id = %s
          AND is_default = 1
        ORDER BY id DESC
        LIMIT 1
        """,
        (user["id"],),
    )

    if request.method == "POST":

        name = request.form.get(
            "recipient_name", ""
        ).strip()

        mobile = request.form.get(
            "mobile_number", ""
        ).strip()

        province = request.form.get(
            "province", ""
        ).strip()

        city = request.form.get(
            "city_municipality", ""
        ).strip()

        barangay = request.form.get(
            "barangay", ""
        ).strip()

        street = request.form.get(
            "street_address", ""
        ).strip()

        postal = request.form.get(
            "postal_code", ""
        ).strip()

        error = None

        # Validate recipient name
        if not valid_name(name, 160):
            error = (
                "Recipient name must contain "
                "letters and spaces only."
            )

        # Validate mobile number
        elif not PHONE_RE.fullmatch(mobile):
            error = (
                "Mobile number must be exactly "
                "11 digits starting with 09."
            )

        # Validate province
        elif not valid_address_text(
            province,
            100
        ):
            error = (
                "Choose a province or region."
            )

        # Validate city
        elif not valid_address_text(
            city,
            100
        ):
            error = (
                "Choose a city or municipality."
            )

        # Validate barangay
        elif not valid_address_text(
            barangay,
            120,
            1
        ):
            error = (
                "Choose a barangay."
            )

        # Validate street address
        elif not valid_address_text(
            street,
            255,
            3
        ):
            error = (
                "Enter a valid house number "
                "and street address."
            )

        # Validate postal code
        elif (
            postal
            and not POSTAL_RE.fullmatch(postal)
        ):
            error = (
                "Postal code must contain "
                "exactly four digits."
            )

        # Validate province, city, barangay
        # against the PSGC API
        elif not valid_selected_address(
            province,
            city,
            barangay
        ):
            error = (
                "Select a valid province, city, "
                "and barangay from the dropdowns."
            )

        if error:
            flash(
                error,
                "danger"
            )

            return render_template(
                "complete_profile.html",
                title="Delivery Address",
                user=user,
                address=address,
            ), 400

        try:

            # Update existing default address
            if address:
                save(
                    """
                    UPDATE customer_addresses
                    SET
                        recipient_name = %s,
                        mobile_number = %s,
                        province = %s,
                        city_municipality = %s,
                        barangay = %s,
                        street_address = %s,
                        postal_code = %s
                    WHERE id = %s
                      AND user_id = %s
                    """,
                    (
                        name,
                        mobile,
                        province,
                        city,
                        barangay,
                        street,
                        postal or None,
                        address["id"],
                        user["id"],
                    ),
                )

            # Add new default address
            else:
                save(
                    """
                    INSERT INTO customer_addresses
                    (
                        user_id,
                        recipient_name,
                        mobile_number,
                        province,
                        city_municipality,
                        barangay,
                        street_address,
                        postal_code,
                        is_default
                    )
                    VALUES
                    (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, 1
                    )
                    """,
                    (
                        user["id"],
                        name,
                        mobile,
                        province,
                        city,
                        barangay,
                        street,
                        postal or None,
                    ),
                )

        except Exception:
            current_app.logger.exception(
                "Saving customer address failed"
            )

            flash(
                "Could not save your address. "
                "Please try again.",
                "danger"
            )

            return render_template(
                "complete_profile.html",
                title="Delivery Address",
                user=user,
                address=address,
            ), 500

        flash(
            "Profile completed successfully!",
            "success"
        )

        return redirect("/")

    return render_template(
        "complete_profile.html",
        title="Delivery Address",
        user=user,
        address=address,
    )

# LOGOUT

@auth_bp.route(
    "/logout",
    methods=["POST"]
)
@login_required
def logout():

    session.clear()

    return redirect(
        url_for("auth.login")
    )
