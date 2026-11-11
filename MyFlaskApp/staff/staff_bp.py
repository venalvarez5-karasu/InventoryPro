import re
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)
from MySQLdb.cursors import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user, role_required
from MyFlaskApp.production.stock_ops import deduct_order_recipe_stock

staff_bp = Blueprint("staff", __name__, template_folder="templates", static_folder="static",)


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
        "SELECT staff_type, is_enabled FROM staff_profiles WHERE user_id = %s",
        (user["id"],),
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
        """INSERT INTO audit_logs
           (user_id, action, entity_name, entity_id, details)
           VALUES (%s, %s, %s, %s, %s)""",
        (user_id, action, entity, entity_id, details[:2000]),
    )


@staff_bp.get("/")
@staff_only
def dashboard():
    user = current_user()
    staff_type = profile(user)["staff_type"]
    if staff_type == "rider":
        orders = get_all(
            """SELECT o.id, o.order_number, o.order_type, o.status,
                      o.recipient_name, o.contact_number,
                      o.delivery_address_snapshot, o.total_amount
               FROM orders o JOIN delivery_assignments d ON d.order_id = o.id
               WHERE d.rider_user_id = %s
                 AND o.order_type = 'delivery'
                 AND o.status IN ('ready', 'out_for_delivery')
               ORDER BY o.created_at DESC LIMIT 100""",
            (user["id"],),
        )
    else:
        orders = get_all(
            """SELECT id, order_number, order_type, status,
                      recipient_name, contact_number,
                      delivery_address_snapshot, total_amount
               FROM orders
               WHERE status IN ('pending', 'confirmed', 'preparing', 'ready')
                  OR (status='completed' AND order_type='delivery'
                      AND payment_method='cod'
                      AND EXISTS (SELECT 1 FROM payments p
                                  WHERE p.order_id=orders.id AND p.status='unpaid'))
               ORDER BY created_at DESC LIMIT 100"""
        )
    return render_template("staff_dashboard.html", view="staff", user=user,
                           staff_type=staff_type, orders=orders)


@staff_bp.post("/orders/<int:order_id>/status")
@staff_only
def change_status(order_id):
    user = current_user()
    staff_type = profile(user)["staff_type"]
    target = request.form.get("status", "")
    conn = mysql.connection
    cur = conn.cursor(DictCursor)
    try:
        conn.begin()
        cur.execute(
            """SELECT id, status, order_type FROM orders
               WHERE id = %s FOR UPDATE""", (order_id,)
        )
        order = cur.fetchone()
        if not order:
            abort(404)

        # Both staff groups share this route, but not the same permissions.
        if staff_type == "bakery":
            allowed = {
                "pending": "confirmed",
                "confirmed": "preparing",
                "preparing": "ready",
            }
            valid = allowed.get(order["status"]) == target
            # A pickup order can only finish after its full payment is recorded.
            if order["order_type"] == "pickup" and order["status"] == "ready" and target == "completed":
                cur.execute(
                    """SELECT o.total_amount,
                           COALESCE(SUM(CASE WHEN p.status='paid' THEN p.amount ELSE 0 END),0) paid
                       FROM orders o LEFT JOIN payments p ON p.order_id=o.id
                       WHERE o.id=%s GROUP BY o.id, o.total_amount""", (order_id,)
                )
                totals = cur.fetchone()
                valid = totals and totals["paid"] >= totals["total_amount"]
        else:
            valid = (order["order_type"] == "delivery" and
                     {"ready": "out_for_delivery",
                      "out_for_delivery": "completed"}.get(order["status"]) == target)
            if valid:
                cur.execute(
                    """SELECT 1 FROM delivery_assignments
                       WHERE order_id=%s AND rider_user_id=%s""",
                    (order_id, user["id"]),
                )
                valid = cur.fetchone() is not None

        if not valid:
            raise ValueError("That action is not allowed for this order or staff account.")
        if target == "confirmed":
            deduct_order_recipe_stock(cur=cur, order_id=order_id,
                                      actor_id=user["id"])
        cur.execute("UPDATE orders SET status=%s WHERE id=%s", (target, order_id))
        audit(cur, user["id"], "staff_order_status", "orders", order_id,
              f"{staff_type}: {order['status']} -> {target}")
        conn.commit()
        flash("Order status updated.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
    except Exception:
        conn.rollback()
        # Do not reveal database internals to staff.
        flash("Unable to update this order. Please contact the admin.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.dashboard"))


@staff_bp.post("/orders/<int:order_id>/payment")
@staff_only
def payment_received(order_id):
    """Record actual COD receipt only after a delivered order is completed."""
    user = current_user()
    if profile(user)["staff_type"] != "bakery":
        abort(403)
    conn = mysql.connection
    cur = conn.cursor(DictCursor)
    try:
        conn.begin()
        cur.execute(
            """SELECT id, status, order_type, payment_method, total_amount
               FROM orders WHERE id=%s FOR UPDATE""", (order_id,),
        )
        order = cur.fetchone()
        if not order or order["status"] != "completed" or order["order_type"] != "delivery" or order["payment_method"] != "cod":
            raise ValueError("Only completed COD deliveries can be marked paid here.")
        cur.execute(
            """SELECT id, status, amount FROM payments
               WHERE order_id=%s ORDER BY id DESC LIMIT 1 FOR UPDATE""",
            (order_id,),
        )
        payment = cur.fetchone()
        if not payment or payment["status"] != "unpaid" or payment["amount"] != order["total_amount"]:
            raise ValueError("Payment is already recorded or needs admin review.")
        cur.execute(
            """UPDATE payments SET status='paid', paid_at=NOW(), verified_by=%s
               WHERE id=%s AND status='unpaid'""",
            (user["id"], payment["id"]),
        )
        if cur.rowcount != 1:
            raise ValueError("Payment changed; refresh the page.")
        audit(cur, user["id"], "staff_payment_received", "orders", order_id,
              "Bakery staff confirmed actual COD receipt")
        conn.commit()
        flash("COD payment recorded.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
    except Exception:
        conn.rollback()
        flash("Could not record payment. Ask the admin to verify.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.dashboard"))


@staff_bp.post("/password")
@staff_only
def change_password():
    user = current_user()
    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    if not (8 <= len(new) <= 128 and any(c.isdigit() for c in new)
            and any(not c.isalnum() and not c.isspace() for c in new)):
        flash("New password needs 8+ characters, a number and a symbol.", "danger")
        return redirect(url_for("staff.dashboard"))
    row = get_one("SELECT password_hash FROM users WHERE id=%s", (user["id"],))
    if not row or not check_password_hash(row["password_hash"], old):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("staff.dashboard"))
    cur = mysql.connection.cursor()
    try:
        cur.execute("UPDATE users SET password_hash=%s WHERE id=%s AND role='staff'",
                    (generate_password_hash(new), user["id"]))
        mysql.connection.commit()
        flash("Password updated.", "success")
    except Exception:
        mysql.connection.rollback()
        flash("Could not update password.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.dashboard"))



@staff_bp.get("/manage")
@role_required("admin")
def manage():
    tab = request.args.get("type", "bakery")

    if tab not in ("bakery", "rider"):
        tab = "bakery"

    per_page = 10

    # Count bakery and rider accounts separately.
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

    bakery_count = int(counts["bakery_count"] or 0)
    rider_count = int(counts["rider_count"] or 0)

    total = (
        bakery_count if tab == "bakery"
        else rider_count
    )

    pages = max(1, (total + per_page - 1) // per_page)

    page = request.args.get(
        "page", default=1, type=int
    ) or 1

    page = max(1, min(page, pages))
    offset = (page - 1) * per_page

    # Only load staff belonging to the selected tab.
    staff = get_all(
        """
        SELECT
            u.id,
            u.first_name,
            u.last_name,
            u.email,
            sp.staff_type,
            sp.is_enabled
        FROM users u
        JOIN staff_profiles sp
            ON sp.user_id = u.id
        WHERE u.role = 'staff'
          AND sp.staff_type = %s
        ORDER BY u.id DESC
        LIMIT %s OFFSET %s
        """,
        (tab, per_page, offset)
    )

    # All active riders are available for assignment,
    # not just the riders on the current page.
    riders = get_all(
        """
        SELECT
            u.id,
            u.first_name,
            u.last_name
        FROM users u
        JOIN staff_profiles sp
            ON sp.user_id = u.id
        WHERE u.role = 'staff'
          AND u.account_status = 'active'
          AND sp.staff_type = 'rider'
          AND sp.is_enabled = 1
        ORDER BY u.first_name, u.last_name
        """
    )

    # Paginate delivery assignments separately.
    assignment_total = int(get_one(
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
    )["total"] or 0)

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
                o.id,
                o.order_number,
                o.status,
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


@staff_bp.post("/manage/create")
@role_required("admin")
def create_staff():
    first = request.form.get("first_name", "").strip()
    last = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    mobile = request.form.get("mobile_number", "").strip()
    password = request.form.get("password", "")
    kind = request.form.get("staff_type", "")
    if not (re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+)*", first)
            and re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+)*", last)
            and len(first) <= 80 and len(last) <= 80
            and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
            and len(email) <= 254
            and re.fullmatch(r"09\d{9}", mobile)
            and 8 <= len(password) <= 128
            and any(c.isdigit() for c in password)
            and any(not c.isalnum() and not c.isspace() for c in password)
            and kind in ("bakery", "rider")):
        flash("Check the name, email, PH phone, password and staff type.", "danger")
        return redirect(
            url_for(
                "staff.manage",
                type=kind if kind in ("bakery", "rider") else "bakery"
                )
            )
    conn = mysql.connection
    cur = conn.cursor(DictCursor)
    try:
        conn.begin()
        cur.execute(
            """SELECT id FROM users WHERE LOWER(email)=%s OR mobile_number=%s
               LIMIT 1""", (email, mobile),
        )
        if cur.fetchone():
            raise ValueError("Email or phone number already registered.")
        cur.execute(
            """INSERT INTO users (first_name,last_name,email,mobile_number,
               password_hash,role,account_status)
               VALUES (%s,%s,%s,%s,%s,'staff','active')""",
            (first,last,email,mobile,generate_password_hash(password)),
        )
        staff_id = cur.lastrowid
        cur.execute(
            "INSERT INTO staff_profiles(user_id,staff_type) VALUES (%s,%s)",
            (staff_id, kind),
        )
        audit(cur, current_user()["id"], "staff_created", "users", staff_id,
              f"staff_type={kind}")
        conn.commit()
        flash("Staff account created. Share the temporary password privately.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
    except Exception:
        conn.rollback()
        flash("Could not create staff. Check database migration and user fields.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.manage"))


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
            """SELECT sp.is_enabled FROM staff_profiles sp
               JOIN users u ON u.id=sp.user_id
               WHERE u.id=%s AND u.role='staff' FOR UPDATE""", (staff_id,),
        )
        p = cur.fetchone()
        if not p:
            abort(404)
        next_enabled = 0 if p["is_enabled"] else 1
        cur.execute("UPDATE staff_profiles SET is_enabled=%s WHERE user_id=%s",
                    (next_enabled, staff_id))
        audit(cur, current_user()["id"], "staff_enabled_changed", "users",
              staff_id, f"enabled={next_enabled}")
        conn.commit()
        flash("Staff access updated.", "success")
    except Exception:
        conn.rollback()
        flash("Could not update staff access.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.manage"))


@staff_bp.post("/manage/assign/<int:order_id>")
@role_required("admin")
def assign_rider(order_id):
    rider_id = request.form.get("rider_id", type=int)
    conn = mysql.connection
    cur = conn.cursor(DictCursor)
    try:
        conn.begin()
        cur.execute("SELECT order_type,status FROM orders WHERE id=%s FOR UPDATE",
                    (order_id,))
        order = cur.fetchone()
        if not order or order["order_type"] != "delivery" or order["status"] not in (
                "confirmed", "preparing", "ready", "out_for_delivery"):
            raise ValueError("Only active delivery orders can be assigned.")
        if rider_id:
            cur.execute(
                """SELECT 1 FROM staff_profiles sp JOIN users u ON u.id=sp.user_id
                   WHERE sp.user_id=%s AND sp.staff_type='rider'
                     AND sp.is_enabled=1 AND u.role='staff'
                     AND u.account_status='active'""", (rider_id,),
            )
            if not cur.fetchone():
                raise ValueError("Select an active rider.")
            cur.execute(
                """INSERT INTO delivery_assignments(order_id,rider_user_id)
                   VALUES (%s,%s) ON DUPLICATE KEY UPDATE
                   rider_user_id=VALUES(rider_user_id)""", (order_id,rider_id),
            )
        else:
            cur.execute("DELETE FROM delivery_assignments WHERE order_id=%s",
                        (order_id,))
        audit(cur, current_user()["id"], "driver_assigned", "orders", order_id,
              f"rider_id={rider_id or 'none'}")
        conn.commit()
        flash("Driver assignment updated.", "success")
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
    except Exception:
        conn.rollback()
        flash("Could not assign driver.", "danger")
    finally:
        cur.close()
    return redirect(url_for("staff.manage"))
