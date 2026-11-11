
import re
from decimal import Decimal
from functools import wraps

from flask import (
    Blueprint, abort, flash, redirect,
    render_template, request, url_for, current_app
)
from MySQLdb.cursors import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user, role_required
from MyFlaskApp.production.stock_ops import deduct_order_recipe_stock


staff_bp = Blueprint(
    "staff",
    __name__,
    template_folder="templates",
    static_folder="static"
)


# ============================================
# DATABASE HELPERS
# ============================================

def get_one(sql, args=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        cur.close()


def get_all(sql, args=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


def profile(user):
    if not user or user["role"] != "staff":
        return None

    return get_one(
        """
        SELECT staff_type, is_enabled
        FROM staff_profiles
        WHERE user_id = %s
        """,
        (user["id"],)
    )


def staff_only(view):
    @wraps(view)
    @role_required("staff")
    def wrapper(*args, **kwargs):
        p = profile(current_user())

        if not p or not p["is_enabled"]:
            abort(403)

        return view(*args, **kwargs)

    return wrapper


def audit(cur, user_id, action, entity, entity_id, details):
    cur.execute(
        """
        INSERT INTO audit_logs (
            user_id, action, entity_name,
            entity_id, details
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user_id, action, entity,
            entity_id, str(details)[:2000]
        )
    )


def active_riders():
    return get_all(
        """
        SELECT u.id, u.first_name, u.last_name
        FROM users u
        JOIN staff_profiles sp ON sp.user_id = u.id
        WHERE u.role = 'staff'
          AND u.account_status = 'active'
          AND sp.staff_type = 'rider'
          AND sp.is_enabled = 1
        ORDER BY u.first_name, u.last_name
        """
    )


# ============================================
# BAKERY / RIDER DASHBOARD
# ============================================

@staff_bp.get("/")
@staff_only
def dashboard():
    user = current_user()
    staff_type = profile(user)["staff_type"]
    riders = []

    if staff_type == "rider":
        orders = get_all(
            """
            SELECT
                o.id,
                o.order_number,
                o.order_type,
                o.status,
                o.recipient_name,
                o.contact_number,
                o.delivery_address_snapshot,
                o.total_amount
            FROM orders o
            INNER JOIN delivery_assignments d
                ON d.order_id = o.id
            WHERE d.rider_user_id = %s
              AND o.order_type = 'delivery'
              AND o.status IN ('ready', 'out_for_delivery')
            ORDER BY o.created_at ASC, o.id ASC
            LIMIT 100
            """,
            (user["id"],)
        )

    else:
        orders = get_all(
            """
            SELECT
                o.id,
                o.order_number,
                o.order_type,
                o.status,
                o.recipient_name,
                o.contact_number,
                o.delivery_address_snapshot,
                o.total_amount,
                d.rider_user_id,
                ru.first_name AS rider_first_name,
                ru.last_name AS rider_last_name
            FROM orders o
            LEFT JOIN delivery_assignments d
                ON d.order_id = o.id
            LEFT JOIN users ru
                ON ru.id = d.rider_user_id
            WHERE o.status IN (
                'pending_verification',
                'pending',
                'confirmed',
                'preparing',
                'ready'
            )
            OR (
                o.status = 'out_for_delivery'
                AND o.order_type = 'delivery'
                AND d.rider_user_id IS NULL
            )
            OR (
                o.status = 'completed'
                AND o.order_type = 'delivery'
                AND o.payment_method = 'cod'
                AND EXISTS (
                    SELECT 1
                    FROM payments p
                    WHERE p.order_id = o.id
                      AND p.status = 'unpaid'
                )
            )
            ORDER BY
                CASE o.status
                    WHEN 'pending_verification' THEN 1
                    WHEN 'pending' THEN 2
                    WHEN 'confirmed' THEN 3
                    WHEN 'preparing' THEN 4
                    WHEN 'ready' THEN 5
                    WHEN 'out_for_delivery' THEN 6
                    ELSE 7
                END,
                o.created_at ASC,
                o.id ASC
            LIMIT 100
            """
        )

        riders = active_riders()

    return render_template(
        "staff_dashboard.html",
        view="staff",
        user=user,
        staff_type=staff_type,
        orders=orders,
        riders=riders
    )


# ============================================
# BAKERY STAFF: ORDER DECISIONS
# ============================================

@staff_bp.post("/orders/<int:order_id>/status")
@staff_only
def change_status(order_id):
    user = current_user()
    staff_type = profile(user)["staff_type"]
    target = request.form.get("status", "").strip()

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT
                id, order_number, status, order_type,
                pickup_deposit_due, pickup_balance_due
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if not order:
            raise ValueError("Order not found.")

        previous = order["status"]

        if staff_type == "bakery":
            allowed = {
                "pending_verification": (
                    "pending", "rejected"
                ),
                "pending": (
                    "confirmed", "rejected"
                ),
                "confirmed": ("preparing",),
                "preparing": ("ready",),
            }

            valid = target in allowed.get(previous, ())

            if (
                order["order_type"] == "pickup"
                and previous == "ready"
                and target == "completed"
            ):
                valid = True

        elif staff_type == "rider":
            allowed = {
                "ready": "out_for_delivery",
                "out_for_delivery": "completed"
            }

            valid = (
                order["order_type"] == "delivery"
                and allowed.get(previous) == target
            )

            if valid:
                cur.execute(
                    """
                    SELECT 1
                    FROM delivery_assignments
                    WHERE order_id = %s
                      AND rider_user_id = %s
                    LIMIT 1
                    """,
                    (order_id, user["id"])
                )

                valid = cur.fetchone() is not None

        else:
            valid = False

        if not valid:
            raise ValueError(
                "This action is not allowed for this order."
            )

        # Rejection of paid orders needs admin/refund review.
        if target == "rejected":
            cur.execute(
                """
                SELECT 1
                FROM payments
                WHERE order_id = %s
                  AND status = 'paid'
                LIMIT 1
                """,
                (order_id,)
            )

            if cur.fetchone():
                raise ValueError(
                    "A payment is already recorded. "
                    "Contact the administrator for refund review."
                )

        # Preserve existing pickup payment safeguards.
        if (
            order["order_type"] == "pickup"
            and target in (
                "confirmed", "preparing", "ready", "completed"
            )
        ):
            deposit_due = Decimal(
                str(order["pickup_deposit_due"] or 0)
            )
            balance_due = Decimal(
                str(order["pickup_balance_due"] or 0)
            )

            if deposit_due <= 0:
                raise ValueError(
                    "Pickup deposit is not configured. "
                    "Please contact the administrator."
                )

            cur.execute(
                """
                SELECT
                    payment_purpose,
                    COALESCE(SUM(amount), 0) AS total_paid
                FROM payments
                WHERE order_id = %s
                  AND status = 'paid'
                  AND payment_purpose IN (
                    'pickup_deposit',
                    'pickup_balance'
                  )
                GROUP BY payment_purpose
                """,
                (order_id,)
            )

            paid = {
                p["payment_purpose"]: Decimal(
                    str(p["total_paid"])
                )
                for p in cur.fetchall()
            }

            if (
                paid.get("pickup_deposit", Decimal("0"))
                < deposit_due
            ):
                raise ValueError(
                    "Verify the required pickup deposit "
                    "before proceeding."
                )

            if (
                target == "completed"
                and paid.get(
                    "pickup_balance", Decimal("0")
                ) < balance_due
            ):
                raise ValueError(
                    "Record the remaining pickup balance "
                    "before completion."
                )

        # Stock is deducted only when confirming.
        if target == "confirmed":
            deduct_order_recipe_stock(
                cur=cur,
                order_id=order_id,
                actor_id=user["id"]
            )

        cur.execute(
            """
            UPDATE orders
            SET status = %s
            WHERE id = %s
            """,
            (target, order_id)
        )

        audit(
            cur,
            user["id"],
            "staff_order_status",
            "orders",
            order_id,
            f"{staff_type}: {previous} -> {target}"
        )

        conn.commit()

        flash(
            "Order status updated successfully.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Staff order status update failed"
        )
        flash(
            "Unable to update order. Please contact admin.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(url_for("staff.dashboard"))


# ============================================
# BAKERY STAFF: ASSIGN DELIVERY RIDER
# ============================================

@staff_bp.post("/orders/<int:order_id>/assign-rider")
@staff_only
def bakery_assign_rider(order_id):
    user = current_user()

    if profile(user)["staff_type"] != "bakery":
        abort(403)

    rider_id = request.form.get("rider_id", type=int)

    if not rider_id or rider_id <= 0:
        flash("Select a valid rider.", "danger")
        return redirect(url_for("staff.dashboard"))

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id, order_number, status, order_type
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if not order:
            raise ValueError("Order not found.")

        if order["order_type"] != "delivery":
            raise ValueError(
                "Only delivery orders can have riders."
            )

        if order["status"] not in (
            "ready", "out_for_delivery"
        ):
            raise ValueError(
                "The order must be Ready before assignment."
            )

        cur.execute(
            """
            SELECT rider_user_id
            FROM delivery_assignments
            WHERE order_id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        existing = cur.fetchone()

        # Once dispatched, assignment is locked
        # unless admin reviews the situation.
        if (
            order["status"] == "out_for_delivery"
            and existing is not None
        ):
            raise ValueError(
                "This delivery is already dispatched. "
                "Ask admin to handle reassignment."
            )

        cur.execute(
            """
            SELECT u.id, u.first_name, u.last_name
            FROM users u
            JOIN staff_profiles sp
                ON sp.user_id = u.id
            WHERE u.id = %s
              AND u.role = 'staff'
              AND u.account_status = 'active'
              AND sp.staff_type = 'rider'
              AND sp.is_enabled = 1
            LIMIT 1
            """,
            (rider_id,)
        )

        rider = cur.fetchone()

        if not rider:
            raise ValueError(
                "Selected rider is inactive or unavailable."
            )

        cur.execute(
            """
            INSERT INTO delivery_assignments (
                order_id, rider_user_id
            )
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                rider_user_id = VALUES(rider_user_id)
            """,
            (order_id, rider_id)
        )

        audit(
            cur,
            user["id"],
            "bakery_rider_assigned",
            "orders",
            order_id,
            (
                f"Order {order['order_number']} assigned to "
                f"{rider['first_name']} {rider['last_name']}"
            )
        )

        conn.commit()
        flash(
            "Rider assigned. The order will appear "
            "in the rider's workspace.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Bakery rider assignment failed"
        )
        flash(
            "Unable to assign rider. Contact admin.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(url_for("staff.dashboard"))


# ============================================
# COD PAYMENT
# ============================================

@staff_bp.post("/orders/<int:order_id>/payment")
@staff_only
def payment_received(order_id):
    user = current_user()

    if profile(user)["staff_type"] != "bakery":
        abort(403)

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT
                id, status, order_type,
                payment_method, total_amount
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if (
            not order
            or order["status"] != "completed"
            or order["order_type"] != "delivery"
            or order["payment_method"] != "cod"
        ):
            raise ValueError(
                "Only completed COD deliveries "
                "can be marked paid here."
            )

        cur.execute(
            """
            SELECT id, status, amount
            FROM payments
            WHERE order_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (order_id,)
        )

        payment = cur.fetchone()

        if (
            not payment
            or payment["status"] != "unpaid"
            or payment["amount"] != order["total_amount"]
        ):
            raise ValueError(
                "Payment already recorded or needs admin review."
            )

        cur.execute(
            """
            UPDATE payments
            SET status = 'paid',
                paid_at = NOW(),
                verified_by = %s
            WHERE id = %s
              AND status = 'unpaid'
            """,
            (user["id"], payment["id"])
        )

        if cur.rowcount != 1:
            raise ValueError(
                "Payment changed. Refresh the page."
            )

        audit(
            cur,
            user["id"],
            "staff_payment_received",
            "orders",
            order_id,
            "Bakery staff confirmed actual COD receipt"
        )

        conn.commit()
        flash("COD payment recorded.", "success")

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "COD payment update failed"
        )
        flash(
            "Could not record payment. Ask admin to verify.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(url_for("staff.dashboard"))


# ============================================
# CHANGE STAFF PASSWORD
# ============================================

@staff_bp.post("/password")
@staff_only
def change_password():
    user = current_user()
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")

    if not (
        8 <= len(new) <= 128
        and any(c.isdigit() for c in new)
        and any(
            not c.isalnum() and not c.isspace()
            for c in new
        )
    ):
        flash(
            "New password requires 8+ characters, "
            "a number, and a symbol.",
            "danger"
        )
        return redirect(url_for("staff.dashboard"))

    row = get_one(
        "SELECT password_hash FROM users WHERE id = %s",
        (user["id"],)
    )

    if (
        not row
        or not check_password_hash(
            row["password_hash"], old
        )
    ):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("staff.dashboard"))

    cur = mysql.connection.cursor()

    try:
        cur.execute(
            """
            UPDATE users
            SET password_hash = %s
            WHERE id = %s AND role = 'staff'
            """,
            (
                generate_password_hash(new),
                user["id"]
            )
        )

        mysql.connection.commit()
        flash("Password updated.", "success")

    except Exception:
        mysql.connection.rollback()
        flash("Could not update password.", "danger")

    finally:
        cur.close()

    return redirect(url_for("staff.dashboard"))


# ============================================
# ADMIN: STAFF MANAGEMENT
# ============================================

@staff_bp.get("/manage")
@role_required("admin")
def manage():
    tab = request.args.get("type", "bakery")

    if tab not in ("bakery", "rider"):
        tab = "bakery"

    per_page = 10

    counts = get_one(
        """
        SELECT
            SUM(sp.staff_type = 'bakery') AS bakery_count,
            SUM(sp.staff_type = 'rider') AS rider_count
        FROM staff_profiles sp
        JOIN users u ON u.id = sp.user_id
        WHERE u.role = 'staff'
        """
    )

    bakery_count = int(
        counts["bakery_count"] or 0
    )
    rider_count = int(
        counts["rider_count"] or 0
    )

    total = (
        bakery_count if tab == "bakery"
        else rider_count
    )

    pages = max(
        1, (total + per_page - 1) // per_page
    )

    page = request.args.get(
        "page", default=1, type=int
    ) or 1

    page = max(1, min(page, pages))
    offset = (page - 1) * per_page

    staff = get_all(
        """
        SELECT
            u.id, u.first_name, u.last_name,
            u.email, sp.staff_type, sp.is_enabled
        FROM users u
        JOIN staff_profiles sp ON sp.user_id = u.id
        WHERE u.role = 'staff'
          AND sp.staff_type = %s
        ORDER BY u.id DESC
        LIMIT %s OFFSET %s
        """,
        (tab, per_page, offset)
    )

    riders = active_riders()

    assignment_total = int(
        get_one(
            """
            SELECT COUNT(*) AS total
            FROM orders
            WHERE order_type = 'delivery'
              AND status IN (
                'confirmed',
                'preparing',
                'ready',
                'out_for_delivery'
              )
            """
        )["total"] or 0
    )

    assignment_pages = max(
        1,
        (assignment_total + per_page - 1) // per_page
    )

    assignment_page = request.args.get(
        "assignment_page", default=1, type=int
    ) or 1

    assignment_page = max(
        1, min(assignment_page, assignment_pages)
    )

    assignment_offset = (
        assignment_page - 1
    ) * per_page

    orders = []

    if tab == "rider":
        orders = get_all(
            """
            SELECT
                o.id, o.order_number, o.status,
                d.rider_user_id
            FROM orders o
            LEFT JOIN delivery_assignments d
                ON d.order_id = o.id
            WHERE o.order_type = 'delivery'
              AND o.status IN (
                'confirmed',
                'preparing',
                'ready',
                'out_for_delivery'
              )
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT %s OFFSET %s
            """,
            (per_page, assignment_offset)
        )

    return render_template(
        "staff_dashboard.html",
        view="admin",
        user=current_user(),
        staff=staff,
        riders=riders,
        orders=orders,
        title="Staff Management",
        tab=tab,
        page=page,
        pages=pages,
        total=total,
        bakery_count=bakery_count,
        rider_count=rider_count,
        assignment_page=assignment_page,
        assignment_pages=assignment_pages,
        assignment_total=assignment_total
    )


# ============================================
# ADMIN: CREATE STAFF ACCOUNT
# ============================================

@staff_bp.post("/manage/create")
@role_required("admin")
def create_staff():
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    mobile = request.form.get("mobile_number", "").strip()
    password = request.form.get("password", "")
    kind = request.form.get("staff_type", "")

    if not (
        re.fullmatch(
            r"[^\W\d_]+(?: [^\W\d_]+)*", first
        )
        and re.fullmatch(
            r"[^\W\d_]+(?: [^\W\d_]+)*", last
        )
        and len(first) <= 80
        and len(last) <= 80
        and re.fullmatch(
            r"[^\s@]+@[^\s@]+\.[^\s@]+", email
        )
        and len(email) <= 254
        and re.fullmatch(r"09\d{9}", mobile)
        and 8 <= len(password) <= 128
        and any(c.isdigit() for c in password)
        and any(
            not c.isalnum() and not c.isspace()
            for c in password
        )
        and kind in ("bakery", "rider")
    ):
        flash(
            "Check name, email, PH phone, "
            "password, and staff type.",
            "danger"
        )
        return redirect(
            url_for(
                "staff.manage",
                type=kind if kind in (
                    "bakery", "rider"
                ) else "bakery"
            )
        )

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id
            FROM users
            WHERE LOWER(email) = %s
               OR mobile_number = %s
            LIMIT 1
            """,
            (email, mobile)
        )

        if cur.fetchone():
            raise ValueError(
                "Email or phone number already registered."
            )

        cur.execute(
            """
            INSERT INTO users (
                first_name, last_name,
                email, mobile_number,
                password_hash,
                role, account_status
            )
            VALUES (
                %s, %s, %s, %s, %s,
                'staff', 'active'
            )
            """,
            (
                first, last, email,
                mobile,
                generate_password_hash(password)
            )
        )

        staff_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO staff_profiles (
                user_id, staff_type
            )
            VALUES (%s, %s)
            """,
            (staff_id, kind)
        )

        audit(
            cur,
            current_user()["id"],
            "staff_created",
            "users",
            staff_id,
            f"staff_type={kind}"
        )

        conn.commit()

        flash(
            "Staff account created. "
            "Share temporary password privately.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Staff creation failed"
        )
        flash(
            "Could not create staff account.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for("staff.manage", type=kind)
    )


# ============================================
# ADMIN: ENABLE / DISABLE STAFF
# ============================================

@staff_bp.post("/manage/<int:staff_id>/toggle")
@role_required("admin")
def toggle_staff(staff_id):
    if staff_id == current_user()["id"]:
        abort(403)

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT sp.is_enabled
            FROM staff_profiles sp
            JOIN users u ON u.id = sp.user_id
            WHERE u.id = %s
              AND u.role = 'staff'
            FOR UPDATE
            """,
            (staff_id,)
        )

        p = cur.fetchone()

        if not p:
            raise ValueError("Staff account not found.")

        next_enabled = (
            0 if p["is_enabled"] else 1
        )

        cur.execute(
            """
            UPDATE staff_profiles
            SET is_enabled = %s
            WHERE user_id = %s
            """,
            (next_enabled, staff_id)
        )

        audit(
            cur,
            current_user()["id"],
            "staff_enabled_changed",
            "users",
            staff_id,
            f"enabled={next_enabled}"
        )

        conn.commit()
        flash("Staff access updated.", "success")

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        flash(
            "Could not update staff access.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(url_for("staff.manage"))


# ============================================
# ADMIN: MANUAL RIDER ASSIGNMENT
# ============================================

@staff_bp.post("/manage/assign/<int:order_id>")
@role_required("admin")
def assign_rider(order_id):
    rider_id = request.form.get(
        "rider_id", type=int
    )

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT order_type, status
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if (
            not order
            or order["order_type"] != "delivery"
            or order["status"] not in (
                "confirmed",
                "preparing",
                "ready",
                "out_for_delivery"
            )
        ):
            raise ValueError(
                "Only active delivery orders "
                "can be assigned."
            )

        if rider_id:
            cur.execute(
                """
                SELECT 1
                FROM staff_profiles sp
                JOIN users u
                    ON u.id = sp.user_id
                WHERE sp.user_id = %s
                  AND sp.staff_type = 'rider'
                  AND sp.is_enabled = 1
                  AND u.role = 'staff'
                  AND u.account_status = 'active'
                """,
                (rider_id,)
            )

            if not cur.fetchone():
                raise ValueError(
                    "Select an active rider."
                )

            cur.execute(
                """
                INSERT INTO delivery_assignments (
                    order_id, rider_user_id
                )
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    rider_user_id = VALUES(rider_user_id)
                """,
                (order_id, rider_id)
            )

        else:
            cur.execute(
                """
                DELETE FROM delivery_assignments
                WHERE order_id = %s
                """,
                (order_id,)
            )

        audit(
            cur,
            current_user()["id"],
            "driver_assigned",
            "orders",
            order_id,
            f"rider_id={rider_id or 'none'}"
        )

        conn.commit()
        flash(
            "Driver assignment updated.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Admin rider assignment failed"
        )
        flash("Could not assign rider.", "danger")

    finally:
        cur.close()

    return redirect(
        url_for("staff.manage", type="rider")
    )
