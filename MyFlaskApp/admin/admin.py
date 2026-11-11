import csv
import io
import re
import unicodedata

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import jsonify
import os
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from flask import (
    Response, abort, current_app, flash,
    redirect, render_template, request, url_for
)
from MySQLdb.cursors import DictCursor
from MySQLdb import IntegrityError

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import (
    current_user, role_required
)
from .admin_bp import (
    admin_bp, db_one, db_all, db_write
)
from MyFlaskApp.production.stock_ops import (
    deduct_order_recipe_stock
)


ORDER_STATUSES = (
    "pending_verification", "pending", "confirmed",
    "preparing", "ready", "out_for_delivery",
    "completed", "cancelled", "rejected"
)

TRANSITIONS = {
    "pending_verification": (
        "pending", "rejected", "cancelled"
    ),
    "pending": (
        "confirmed", "rejected", "cancelled"
    ),
    "confirmed": ("preparing",),
    "preparing": ("ready",),
    "ready": ("out_for_delivery", "completed"),
    "out_for_delivery": ("completed",),
}

# SHARED HELPERS

def actor_id():
    user = current_user()

    if isinstance(user, dict):
        return user.get("id")

    return getattr(user, "id", None)


def audit(action, entity, entity_id=None, details=""):
    try:
        db_write(
            """
            INSERT INTO audit_logs
            (user_id, action, entity_name, entity_id, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                action,
                entity,
                entity_id,
                str(details)[:2000],
            ),
        )
    except Exception:
        current_app.logger.exception(
            "Could not write admin audit entry"
        )


def money(value, allow_zero=True):
    try:
        result = Decimal(str(value).strip())

        if (
            not result.is_finite()
            or result < 0
            or (not allow_zero and result == 0)
            or result > Decimal("99999999.99")
        ):
            raise ValueError

        rounded = result.quantize(Decimal("0.01"))

        if rounded != result:
            raise ValueError

        return rounded

    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Enter a valid amount with up to two decimals."
        )


def quantity(value, allow_zero=False):
    try:
        result = Decimal(str(value).strip())

        if (
            not result.is_finite()
            or result < 0
            or (not allow_zero and result == 0)
            or result > Decimal("999999999.999")
        ):
            raise ValueError

        rounded = result.quantize(Decimal("0.001"))

        if rounded != result or (
            not allow_zero and rounded == 0
        ):
            raise ValueError

        return rounded

    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Enter a valid quantity with up to "
            "three decimal places."
        )


def page_number():
    return min(
        100000,
        max(
            1,
            request.args.get(
                "page", default=1, type=int
            ) or 1
        )
    )

# ADMIN PAGINATION - 10 RECORDS PER PAGE

ADMIN_PAGE_SIZE = 10


def get_page_info(total):
    total = int(total or 0)

    pages = max(
        1,
        (total + ADMIN_PAGE_SIZE - 1)
        // ADMIN_PAGE_SIZE
    )

    page = min(page_number(), pages)

    offset = (page - 1) * ADMIN_PAGE_SIZE

    return page, pages, offset


def console(section, title, **kwargs):
    return render_template(
        "admin_console.html",
        section=section,
        title=title,
        user=current_user(),
        **kwargs
    )


def make_slug(value):
    value = unicodedata.normalize("NFKD", value)

    value = value.encode(
        "ascii", "ignore"
    ).decode("ascii")

    return re.sub(
        r"[^a-z0-9]+", "-", value.lower()
    ).strip("-")[:100]

# CATEGORY MANAGEMENT

@admin_bp.route(
    "/categories",
    methods=["GET", "POST"]
)
@role_required("admin")
def categories_page():

    if request.method == "POST":
        action = request.form.get("action", "")
        category_id = request.form.get(
            "category_id", type=int
        )

        try:
            if action in ("add", "update"):

                name = request.form.get(
                    "name", ""
                ).strip()

                if not 2 <= len(name) <= 100:
                    raise ValueError(
                        "Category name must be "
                        "2 to 100 characters."
                    )

                try:
                    position = int(
                        request.form.get(
                            "display_order", "0"
                        )
                    )
                except ValueError:
                    raise ValueError(
                        "Display order must be a number."
                    )

                if not 0 <= position <= 9999:
                    raise ValueError(
                        "Display order must be "
                        "between 0 and 9999."
                    )

                if action == "add":

                    slug = make_slug(name)

                    if not slug:
                        raise ValueError(
                            "Use a valid category name."
                        )

                    new_id = db_write(
                        """
                        INSERT INTO product_categories
                        (name, slug, display_order)
                        VALUES (%s, %s, %s)
                        """,
                        (name, slug, position),
                    )

                    audit(
                        "category_created",
                        "product_categories",
                        new_id,
                        name
                    )

                else:
                    existing = db_one(
                        """
                        SELECT id
                        FROM product_categories
                        WHERE id = %s
                        """,
                        (category_id,),
                    )

                    if not existing:
                        abort(404)

                    # Preserve slug to avoid breaking
                    # existing customer filter links.
                    db_write(
                        """
                        UPDATE product_categories
                        SET name = %s,
                            display_order = %s
                        WHERE id = %s
                        """,
                        (
                            name,
                            position,
                            category_id,
                        ),
                    )

                    audit(
                        "category_updated",
                        "product_categories",
                        category_id,
                        name
                    )

            elif action in ("disable", "enable"):

                if not category_id:
                    abort(404)

                existing = db_one(
                    "SELECT id FROM product_categories "
                    "WHERE id=%s",
                    (category_id,),
                )

                if not existing:
                    abort(404)

                if action == "disable":

                    count = db_one(
                        """
                        SELECT COUNT(*) AS n
                        FROM products
                        WHERE category_id = %s
                        """,
                        (category_id,),
                    )["n"]

                    if count:
                        raise ValueError(
                            "Move all products out of "
                            "this category first."
                        )

                db_write(
                    """
                    UPDATE product_categories
                    SET is_active = %s
                    WHERE id = %s
                    """,
                    (
                        1 if action == "enable" else 0,
                        category_id
                    ),
                )

                audit(
                    "category_" + action,
                    "product_categories",
                    category_id
                )

            else:
                raise ValueError(
                    "Unknown category action."
                )

            flash(
                "Category saved successfully.",
                "success"
            )

        except (ValueError, IntegrityError) as exc:
            if isinstance(exc, IntegrityError):
                flash(
                    "Invalid or duplicate category details.",
                    "danger"
                )
            else:
                flash(str(exc), "danger")

        return redirect(
            url_for("admin.categories_page")
        )

    # List ten categories at a time; existing POST actions are unchanged.
    total = db_one(
        "SELECT COUNT(*) AS n FROM product_categories"
    )["n"]

    page, pages, offset = get_page_info(total)

    rows = db_all(
        """
        SELECT c.*,
        (
            SELECT COUNT(*)
            FROM products p
            WHERE p.category_id = c.id
        ) AS product_count
        FROM product_categories c
        ORDER BY c.display_order, c.name, c.id
        LIMIT %s OFFSET %s
        """,
        (ADMIN_PAGE_SIZE, offset),
    )

    return console(
        "categories",
        "Product Categories",
        rows=rows,
        page=page,
        pages=pages,
        total=total,
    )

# ORDER MANAGEMENT

@admin_bp.route("/orders")
@role_required("admin")
def admin_orders():

    status = request.args.get(
        "status", ""
    ).strip()

    if status not in ORDER_STATUSES:
        status = ""

    q = request.args.get(
        "q", ""
    ).strip()[:80]

    where = ["1=1"]
    params = []

    if status:
        where.append("o.status = %s")
        params.append(status)

    if q:
        where.append(
            "("
            "o.order_number LIKE %s "
            "OR o.recipient_name LIKE %s "
            "OR u.email LIKE %s"
            ")"
        )

        params.extend([f"%{q}%"] * 3)

    condition = " AND ".join(where)

    total = db_one(
        f"""
        SELECT COUNT(*) AS n
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE {condition}
        """,
        tuple(params),
    )["n"]

    page, pages, offset = get_page_info(total)

    rows = db_all(
        f"""
        SELECT
            o.id,
            o.order_number,
            o.status,
            o.order_type,
            o.payment_method,
            o.total_amount,
            o.created_at,
            o.recipient_name,
            u.email
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE {condition}
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [ADMIN_PAGE_SIZE, offset]),
    )

    return console(
        "orders",
        "Order Management",
        rows=rows,
        q=q,
        status=status,
        statuses=ORDER_STATUSES,
        page=page,
        pages=pages,
        total=total
    )


@admin_bp.route("/orders/<int:order_id>")
@role_required("admin")
def admin_orderdetail(order_id):

    order = db_one(
        """
        SELECT
            o.*,
            u.email,
            u.first_name,
            u.last_name
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.id = %s
        """,
        (order_id,),
    )

    if not order:
        abort(404)

    items = db_all(
        """
        SELECT *
        FROM order_items
        WHERE order_id = %s
        ORDER BY id
        """,
        (order_id,),
    )

    payments = db_all(
        """
        SELECT *
        FROM payments
        WHERE order_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    )

    allowed = list(
        TRANSITIONS.get(
            order["status"], ()
        )
    )

    if order["order_type"] == "pickup":
        if "out_for_delivery" in allowed:
            allowed.remove("out_for_delivery")

    if (
        order["order_type"] == "delivery"
        and order["status"] == "ready"
        and "completed" in allowed
    ):
        allowed.remove("completed")
        
    
    # Hide unavailable pickup transitions in the UI.
    # The POST route independently enforces these rules.

    if order["order_type"] == "pickup":

        deposit_due = Decimal(
            str(order["pickup_deposit_due"] or 0)
        )

        balance_due = Decimal(
            str(order["pickup_balance_due"] or 0)
        )

        deposit_paid = sum(
            (
                Decimal(str(p["amount"]))
                for p in payments
                if p["payment_purpose"] == "pickup_deposit"
                and p["status"] == "paid"
            ),
            Decimal("0")
        )

        balance_paid = sum(
            (
                Decimal(str(p["amount"]))
                for p in payments
                if p["payment_purpose"] == "pickup_balance"
                and p["status"] == "paid"
            ),
            Decimal("0")
        )

        if (
            deposit_due <= 0
            or deposit_paid < deposit_due
        ):
            allowed = [
                status
                for status in allowed
                if status in ("cancelled", "rejected")
            ]

        elif balance_paid < balance_due:
            allowed = [
                status
                for status in allowed
                if status != "completed"
            ]


    return render_template(
        "admin_orderdetail.html",
        title="Order Details",
        user=current_user(),
        order=order,
        items=items,
        payments=payments,
        allowed=allowed
    )


@admin_bp.route(
    "/orders/<int:order_id>/status",
    methods=["POST"]
)
@role_required("admin")
def admin_order_status(order_id):

    target = request.form.get("status", "")

    if target not in ORDER_STATUSES:
        flash("Invalid order status.", "danger")

        return redirect(
            url_for(
                "admin.admin_orderdetail",
                order_id=order_id
            )
        )

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT status, order_type
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,),
        )

        row = cur.fetchone()

        if not row:
            raise ValueError("Order not found.")

        allowed = TRANSITIONS.get(
            row["status"], ()
        )

        if row["order_type"] == "pickup":
            allowed = tuple(
                s for s in allowed
                if s != "out_for_delivery"
            )

        if (
            row["order_type"] == "delivery"
            and row["status"] == "ready"
        ):
            allowed = tuple(
                s for s in allowed
                if s != "completed"
            )

        if target not in allowed:
            raise ValueError(
                "This order status change "
                "is not allowed."
            )
            
         
        # PICKUP PAYMENT SAFETY
        # Delivery COD is not affected.

        if row["order_type"] == "pickup":

            cur.execute(
                """
                SELECT
                    pickup_deposit_due,
                    pickup_balance_due
                FROM orders
                WHERE id = %s
                """,
                (order_id,)
            )

            amounts = cur.fetchone()

            deposit_due = Decimal(
                str(amounts["pickup_deposit_due"] or 0)
            )

            balance_due = Decimal(
                str(amounts["pickup_balance_due"] or 0)
            )

            if deposit_due <= 0:
                raise ValueError(
                    "Pickup deposit is not configured "
                    "for this order."
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

            paid_amounts = {
                payment["payment_purpose"]: Decimal(
                    str(payment["total_paid"])
                )
                for payment in cur.fetchall()
            }

            deposit_paid = paid_amounts.get(
                "pickup_deposit", Decimal("0.00")
            )

            balance_paid = paid_amounts.get(
                "pickup_balance", Decimal("0.00")
            )

            # Cancellation/rejection remains possible
            # under the existing transition rules.
            if target not in ("cancelled", "rejected"):

                if deposit_paid < deposit_due:
                    raise ValueError(
                        "Verify the required pickup deposit "
                        "before advancing this order."
                    )

                # Complete pickup only after the
                # remaining balance was collected.
                if (
                    target == "completed"
                    and balance_paid < balance_due
                ):
                    raise ValueError(
                        "Record the remaining pickup balance "
                        "before completing this order."
                    )
   
            
            
        if target == "confirmed":
            deduct_order_recipe_stock(    
                cur=cur,
                order_id=order_id,
                actor_id=actor_id(),
            )    

        cur.execute(
            """
            UPDATE orders
            SET status = %s
            WHERE id = %s
            """,
            (target, order_id),
        )

        cur.execute(
            """
            INSERT INTO audit_logs
            (user_id, action, entity_name,
             entity_id, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "order_status_changed",
                "orders",
                order_id,
                f"{row['status']} -> {target}",
            ),
        )

        conn.commit()

        flash(
            "Order status updated.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Order update failed"
        )
        flash("Order update failed.", "danger")

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_orderdetail",
            order_id=order_id
        )
    )

# ==========================================
# STORE PICKUP - VERIFY OR REJECT DEPOSIT
# ==========================================

@admin_bp.route(
    "/orders/<int:order_id>/deposit-review",
    methods=["POST"]
)
@role_required("admin")
def admin_pickup_deposit_review(order_id):

    payment_id = request.form.get(
        "payment_id", type=int
    )

    decision = request.form.get("decision", "").strip()

    if not payment_id or decision not in {
        "verify", "reject"
    }:
        abort(400)

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT
                id,
                order_type,
                status,
                payment_method,
                pickup_deposit_due
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if not order:
            raise ValueError("Order not found.")

        if order["order_type"] != "pickup":
            raise ValueError(
                "Deposit verification is for Store Pickup only."
            )

        if order["status"] in (
            "completed", "cancelled", "rejected"
        ):
            raise ValueError(
                "This pickup order is no longer eligible "
                "for deposit review."
            )

        cur.execute(
            """
            SELECT
                id,
                amount,
                status,
                payment_method,
                payment_reference
            FROM payments
            WHERE id = %s
              AND order_id = %s
              AND payment_purpose = 'pickup_deposit'
            FOR UPDATE
            """,
            (payment_id, order_id)
        )

        payment = cur.fetchone()

        if not payment:
            raise ValueError(
                "Deposit payment record not found."
            )

        if payment["status"] != "pending_review":
            raise ValueError(
                "Only pending-review deposits "
                "can be verified or rejected."
            )

        required = Decimal(
            str(order["pickup_deposit_due"] or 0)
        ).quantize(Decimal("0.01"))

        submitted = Decimal(
            str(payment["amount"])
        ).quantize(Decimal("0.01"))

        if (
            required <= 0
            or submitted != required
            or not payment["payment_reference"]
            or payment["payment_method"]
               != order["payment_method"]
        ):
            raise ValueError(
                "Deposit amount, reference or method "
                "does not match the pickup order."
            )

        if decision == "verify":

            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM payments
                WHERE order_id = %s
                  AND payment_purpose = 'pickup_deposit'
                  AND status = 'paid'
                """,
                (order_id,)
            )

            existing_paid = Decimal(
                str(cur.fetchone()["total"])
            )

            if existing_paid > 0:
                raise ValueError(
                    "A verified deposit already exists."
                )

            cur.execute(
                """
                UPDATE payments
                SET
                    status = 'paid',
                    verified_by = %s,
                    paid_at = NOW()
                WHERE id = %s
                """,
                (actor_id(), payment_id)
            )

            action = "pickup_deposit_verified"
            message = "Pickup deposit verified."

        else:

            cur.execute(
                """
                UPDATE payments
                SET
                    status = 'failed',
                    verified_by = %s
                WHERE id = %s
                """,
                (actor_id(), payment_id)
            )

            action = "pickup_deposit_rejected"
            message = "Deposit submission rejected."

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                action,
                "payments",
                payment_id,
                f"Order #{order_id}; decision={decision}"
            )
        )

        conn.commit()
        flash(message, "success")

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Pickup deposit review failed."
        )
        flash(
            "Unable to review the pickup deposit.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_orderdetail",
            order_id=order_id
        )
    )

# ==========================================
# STORE PICKUP - COLLECT REMAINING BALANCE
# ==========================================

@admin_bp.route(
    "/orders/<int:order_id>/pickup-balance",
    methods=["POST"]
)
@role_required("admin")
def admin_pickup_balance_received(order_id):

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT
                id,
                order_type,
                status,
                pickup_deposit_due,
                pickup_balance_due
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,)
        )

        order = cur.fetchone()

        if not order:
            raise ValueError("Order not found.")

        if (
            order["order_type"] != "pickup"
            or order["status"] != "ready"
        ):
            raise ValueError(
                "The pickup order must be ready "
                "before collecting the balance."
            )

        deposit_due = Decimal(
            str(order["pickup_deposit_due"] or 0)
        )

        balance_due = Decimal(
            str(order["pickup_balance_due"] or 0)
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
                  'pickup_deposit', 'pickup_balance'
              )
            GROUP BY payment_purpose
            """,
            (order_id,)
        )

        recorded = {
            row["payment_purpose"]: Decimal(
                str(row["total_paid"])
            )
            for row in cur.fetchall()
        }

        if (
            deposit_due <= 0
            or recorded.get(
                "pickup_deposit", Decimal("0")
            ) < deposit_due
        ):
            raise ValueError(
                "The pickup deposit must be verified first."
            )

        if recorded.get(
            "pickup_balance", Decimal("0")
        ) > 0:
            raise ValueError(
                "The remaining balance was already recorded."
            )

        if balance_due <= 0:
            raise ValueError(
                "There is no remaining balance to collect."
            )

        # Cash is recorded only after the bakery
        # physically receives the payment.
        cur.execute(
            """
            INSERT INTO payments
            (
                order_id,
                payment_method,
                amount,
                status,
                payment_purpose,
                verified_by,
                paid_at
            )
            VALUES
            (
                %s,
                'cash_on_pickup',
                %s,
                'paid',
                'pickup_balance',
                %s,
                NOW()
            )
            """,
            (
                order_id,
                balance_due,
                actor_id()
            )
        )

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id, action,
                entity_name, entity_id, details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "pickup_balance_received",
                "orders",
                order_id,
                f"Cash received: PHP {balance_due}"
            )
        )

        conn.commit()

        flash(
            "Remaining pickup balance recorded.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Could not record pickup balance."
        )
        flash(
            "Unable to record pickup balance.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_orderdetail",
            order_id=order_id
        )
    )

# MANUAL PAYMENT CONFIRMATION

@admin_bp.route(
    "/orders/<int:order_id>/payment",
    methods=["POST"]
)
@role_required("admin")
def admin_payment_received(order_id):

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id, status, payment_method,
                   total_amount
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,),
        )

        order = cur.fetchone()

        if not order:
            raise ValueError("Order not found.")

        if order["status"] != "completed":
            raise ValueError(
                "Complete the order before "
                "recording payment received."
            )

        cur.execute(
            """
            SELECT id, status
            FROM payments
            WHERE order_id = %s
            ORDER BY id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (order_id,),
        )
        
        

        payment = cur.fetchone()

        if payment and payment["status"] == "paid":
            raise ValueError(
                "Payment is already marked as paid."
            )

        if payment:
            cur.execute(
                """
                UPDATE payments
                SET
                    status = 'paid',
                    paid_at = NOW(),
                    verified_by = %s
                WHERE id = %s
                """,
                (
                    actor_id(),
                    payment["id"]
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO payments
                (
                    order_id,
                    payment_method,
                    amount,
                    status,
                    verified_by,
                    paid_at
                )
                VALUES
                (%s, %s, %s, 'paid', %s, NOW())
                """,
                (
                    order_id,
                    order["payment_method"],
                    order["total_amount"],
                    actor_id(),
                ),
            )

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "payment_marked_paid",
                "orders",
                order_id,
                "Manually confirmed receipt",
            ),
        )

        conn.commit()

        flash(
            "Payment marked received.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Payment update failed"
        )
        flash(
            "Could not update payment.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_orderdetail",
            order_id=order_id
        )
    )

# CUSTOMER MANAGEMENT

@admin_bp.route("/customers")
@role_required("admin")
def admin_customers():

    q = request.args.get(
        "q", ""
    ).strip()[:80]

    params = []
    where = "role = 'customer'"

    if q:
        where += (
            " AND ("
            "email LIKE %s "
            "OR first_name LIKE %s "
            "OR last_name LIKE %s"
            ")"
        )

        params = [f"%{q}%"] * 3

    total = db_one(
        f"""
        SELECT COUNT(*) AS n
        FROM users
        WHERE {where}
        """,
        tuple(params),
    )["n"]

    page, pages, offset = get_page_info(total)

    rows = db_all(
        f"""
        SELECT
            id,
            first_name,
            last_name,
            email,
            mobile_number,
            account_status,
            email_verified_at,
            created_at
        FROM users
        WHERE {where}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [ADMIN_PAGE_SIZE, offset]),
    )

    return console(
        "customers",
        "Customers",
        rows=rows,
        q=q,
        page=page,
        pages=pages,
        total=total
    )

@admin_bp.route(
    "/customers/<int:user_id>/status",
    methods=["POST"]
)
@role_required("admin")
def admin_customer_status(user_id):

    target = request.form.get(
        "status", ""
    )

    if target not in ("active", "disabled"):
        abort(400)

    customer = db_one(
        """
        SELECT id, role
        FROM users
        WHERE id = %s
        """,
        (user_id,),
    )

    if (
        not customer
        or customer["role"] != "customer"
    ):
        abort(403)

    db_write(
        """
        UPDATE users
        SET account_status = %s
        WHERE id = %s AND role = 'customer'
        """,
        (target, user_id),
    )

    audit(
        "customer_status_changed",
        "users",
        user_id,
        target
    )

    flash(
        "Customer status updated.",
        "success"
    )

    return redirect(
        url_for("admin.admin_customers")
    )


# ==========================================
# AUTOMATIC DELIVERY PRICING
# ==========================================

def delivery_distance(value):
    """
    Parse an admin-supplied estimated road distance.
    This is not a live map calculation.
    """
    if value is None or not str(value).strip():
        return None

    try:
        distance = Decimal(str(value).strip())

        if (
            not distance.is_finite()
            or distance < 0
            or distance > Decimal("99999.99")
            or distance.quantize(Decimal("0.01")) != distance
        ):
            raise ValueError

        return distance

    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Enter a valid estimated distance "
            "in kilometers with up to 2 decimals."
        )


def calculate_delivery_fee(distance, settings):
    """
    Delivery fee = base fee + (distance x rate per km).

    The value is calculated on the server.
    Client-side fee previews are informational only.
    """
    if distance is None:
        return None

    if not settings:
        raise ValueError(
            "Configure the delivery pricing rule first."
        )

    base_fee = Decimal(str(settings["base_fee"]))
    per_km = Decimal(str(settings["rate_per_km"]))

    fee = (
        base_fee + distance * per_km
    ).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    if fee < 0 or fee > Decimal("99999999.99"):
        raise ValueError(
            "Calculated delivery fee is outside "
            "the allowed range."
        )

    return fee


# ==========================================
# SAVE GLOBAL DELIVERY PRICING
# ==========================================

# ==========================================
# DELIVERY AREAS - DISTANCE TIER PRICING
# Fixed origin: Los Banos, Laguna
# ==========================================

DELIVERY_FEE_TIERS = (
    (Decimal("5"), Decimal("15.00")),
    (Decimal("15"), Decimal("20.00")),
    (Decimal("25"), Decimal("30.00")),
    (Decimal("50"), Decimal("40.00")),
    (Decimal("75"), Decimal("50.00")),
    (Decimal("100"), Decimal("65.00")),
)

NCR_CITY_NAMES = {
    "manila",
    "city of manila",
    "quezon city",
    "makati",
    "pasig",
    "pasay",
    "taguig",
    "mandaluyong",
    "marikina",
    "muntinlupa",
    "paranaque",
    "parañaque",
    "las pinas",
    "las piñas",
    "caloocan",
    "malabon",
    "navotas",
    "valenzuela",
    "san juan",
    "pateros",
}


def delivery_distance(value):
    """Validate an Admin-supplied road-distance estimate."""

    if value is None or not str(value).strip():
        return None

    try:
        distance = Decimal(str(value).strip())

        if (
            not distance.is_finite()
            or distance < 0
            or distance > Decimal("99999.99")
            or distance.quantize(Decimal("0.01")) != distance
        ):
            raise ValueError

        return distance

    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            "Enter a valid distance in kilometers "
            "with up to two decimal places."
        )


def get_delivery_fee(distance):
    """
    Return the approved customer delivery fee.

    Beyond 100 km, return None:
    quotation required, not automatic checkout.
    """

    if distance is None:
        return None

    for maximum_km, fee in DELIVERY_FEE_TIERS:
        if distance <= maximum_km:
            return fee

    return None

# ==========================================
# OPTIONAL AUTOMATIC ROAD DISTANCE
# ==========================================

def auto_road_distance(region_id, city):
    """
    Calculate a driving route from the
    Los Banos town center to a destination
    municipality center.

    Returns None when routing is unavailable.
    Does not overwrite existing local distances.
    """

    api_key = os.getenv("GEOAPIFY_API_KEY", "").strip()

    if not api_key:
        return None

    region = db_one(
        """
        SELECT name
        FROM service_regions
        WHERE id = %s AND is_active = 1
        """,
        (region_id,)
    )

    if not region:
        return None

    region_name = region["name"]

    # Approximate Los Banos town-center coordinates.
    # Replace these with the bakery's verified
    # coordinates for more accurate routing.
    origin_lat = 14.170
    origin_lon = 121.242

    def normalize(text):
        return "".join(
            character
            for character in unicodedata.normalize(
                "NFKD", str(text).casefold()
            )
            if character.isalnum()
        )

    def request_json(endpoint, parameters):
        url = endpoint + "?" + urlencode(parameters)

        request_object = Request(
            url,
            headers={
                "User-Agent": "InventoryPro/1.0",
                "Accept": "application/json"
            }
        )

        with urlopen(request_object, timeout=12) as response:
            return json.load(response)

    try:
        if (
            normalize(region_name).startswith("laguna")
            and normalize(city) == "losbanos"
        ):
            return Decimal("0.00")

        # Find coordinates of the selected city.
        result = request_json(
            "https://api.geoapify.com/v1/geocode/search",
            {
                "text": (
                    f"{city}, {region_name}, Philippines"
                ),
                "filter": "countrycode:ph",
                "limit": 5,
                "apiKey": api_key
            }
        )

        features = result.get("features", [])

        selected = None
        expected_city = normalize(city)

        region_check = (
            "metro manila"
            if "ncr" in region_name.casefold()
            else region_name.casefold()
        )

        for feature in features:
            properties = feature.get("properties", {})

            names = [
                properties.get("city", ""),
                properties.get("name", ""),
                properties.get("municipality", ""),
                properties.get("town", "")
            ]

            location_text = " ".join(
                str(properties.get(field, ""))
                for field in (
                    "formatted",
                    "county",
                    "state",
                    "suburb"
                )
            ).casefold()

            matching_city = any(
                normalize(name) == expected_city
                for name in names
            )

            matching_region = (
                region_check in location_text
            )

            if matching_city and matching_region:
                selected = feature
                break

        if selected is None:
            return None

        coordinates = selected["geometry"]["coordinates"]

        destination_lon = float(coordinates[0])
        destination_lat = float(coordinates[1])

        # Reject coordinates outside the Philippines.
        if not (
            116 <= destination_lon <= 127
            and 5 <= destination_lat <= 21
        ):
            return None

        # Calculate actual route length along roads.
        route = request_json(
            "https://api.geoapify.com/v1/routing",
            {
                "waypoints": (
                    f"{origin_lat},{origin_lon}|"
                    f"{destination_lat},{destination_lon}"
                ),
                "mode": "drive",
                "format": "json",
                "apiKey": api_key
            }
        )

        routes = route.get("results", [])

        if not routes:
            return None

        distance_meters = Decimal(
            str(routes[0]["distance"])
        )

        if not distance_meters.is_finite():
            return None

        distance_km = (
            distance_meters / Decimal("1000")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        if not 0 <= distance_km <= 99999.99:
            return None

        return distance_km

    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        InvalidOperation
    ):
        current_app.logger.warning(
            "Automatic road routing unavailable for %s, %s",
            city,
            region_name
        )

        return None


def lookup_delivery_distance(region_id, city):
    """Look up a previously saved local route estimate."""

    if not region_id or not city:
        return auto_road_distance(region_id, city)

    result = db_one(
        """
        SELECT distance_km
        FROM delivery_route_distances
        WHERE region_id = %s
          AND LOWER(TRIM(city_municipality))
              = LOWER(TRIM(%s))
        LIMIT 1
        """,
        (region_id, city)
    )

    if result:
        return Decimal(str(result["distance_km"]))

    # Fall back to distances already saved on
    # existing delivery areas.
    result = db_one(
        """
        SELECT estimated_distance_km
        FROM service_areas
        WHERE region_id = %s
          AND LOWER(TRIM(city_municipality))
              = LOWER(TRIM(%s))
          AND estimated_distance_km IS NOT NULL
        LIMIT 1
        """,
        (region_id, city)
    )

    if result:
        return Decimal(
            str(result["estimated_distance_km"])
        )

    return None


def validate_delivery_city_region(city, region_name):
    """
    Prevent a common mistake:
    NCR cities being assigned to another province.
    """

    normalized_city = " ".join(
        city.strip().casefold().split()
    )

    if normalized_city not in NCR_CITY_NAMES:
        return

    normalized_region = region_name.casefold()

    is_ncr = (
        "metro manila" in normalized_region
        or "ncr" in normalized_region
        or normalized_region.strip() == "national capital region"
    )

    if not is_ncr:
        raise ValueError(
            f"{city} is in Metro Manila (NCR). "
            "Please select the correct region."
        )


# ==========================================
# AUTOMATIC DISTANCE LOOKUP ENDPOINT
# ==========================================

@admin_bp.route(
    "/delivery-distance-lookup",
    methods=["GET"]
)
@role_required("admin")
def admin_delivery_distance_lookup():

    region_id = request.args.get(
        "region_id", type=int
    )

    city = request.args.get(
        "city", ""
    ).strip()

    if (
        not region_id
        or len(city) < 2
        or len(city) > 100
    ):
        return jsonify({
            "found": False,
            "distance_km": None,
        })

    region = db_one(
        """
        SELECT name
        FROM service_regions
        WHERE id = %s
          AND is_active = 1
        """,
        (region_id,)
    )

    if not region:
        return jsonify({
            "found": False,
            "message": "Select a valid region."
        }), 400

    try:
        validate_delivery_city_region(
            city,
            region["name"]
        )

        distance = lookup_delivery_distance(
            region_id,
            city
        )

    except ValueError as exc:
        return jsonify({
            "found": False,
            "message": str(exc)
        }), 400

    if distance is None:
        return jsonify({
            "found": False,
            "distance_km": None,
            "message": (
                "No locally saved distance for this city. "
                "Enter a checked road-distance estimate once."
            ),
        })

    fee = get_delivery_fee(distance)

    return jsonify({
        "found": True,
        "distance_km": str(distance),
        "fee": str(fee) if fee is not None else None,
        "quotation_required": fee is None,
        "message": "Saved local distance found."
    })


# ==========================================
# ADD / EDIT DELIVERY AREA
# ==========================================

@admin_bp.route(
    "/delivery-areas",
    methods=["GET", "POST"]
)
@role_required("admin")
def admin_delivery_areas():

    if request.method == "POST":

        action = request.form.get(
            "action", ""
        ).strip()

        area_id = request.form.get(
            "area_id", type=int
        )

        try:
            if action not in ("add", "update"):
                raise ValueError(
                    "Invalid delivery area action."
                )

            region_id = request.form.get(
                "region_id", type=int
            )

            city = " ".join(
                request.form.get(
                    "city_municipality", ""
                ).strip().split()
            )

            if not region_id:
                raise ValueError(
                    "Please select a province or region."
                )

            region = db_one(
                """
                SELECT id, name
                FROM service_regions
                WHERE id = %s
                  AND is_active = 1
                """,
                (region_id,)
            )

            if not region:
                raise ValueError(
                    "The selected region is not available."
                )

            if not 2 <= len(city) <= 100:
                raise ValueError(
                    "City or municipality must be "
                    "2 to 100 characters long."
                )

            validate_delivery_city_region(
                city,
                region["name"]
            )

            # Check for an existing service area.
            existing = None

            if action == "update":
                if not area_id:
                    raise ValueError(
                        "Delivery area ID is missing."
                    )

                existing = db_one(
                    """
                    SELECT
                        id,
                        region_id,
                        city_municipality,
                        estimated_distance_km,
                        delivery_fee
                    FROM service_areas
                    WHERE id = %s
                    """,
                    (area_id,)
                )

                if not existing:
                    raise ValueError(
                        "The delivery area was not found."
                    )

            # Prevent duplicate region + city.
            duplicate = db_one(
                """
                SELECT id
                FROM service_areas
                WHERE region_id = %s
                  AND LOWER(TRIM(city_municipality))
                      = LOWER(TRIM(%s))
                LIMIT 1
                """,
                (region_id, city)
            )

            if duplicate and (
                action == "add"
                or int(duplicate["id"]) != area_id
            ):
                raise ValueError(
                    "This city is already configured. "
                    "Use Edit instead of Add Area."
                )

            # A manually supplied km value takes
            # priority over locally saved data.
            distance = delivery_distance(
                request.form.get(
                    "estimated_distance_km", ""
                )
            )

            if distance is None:
                distance = lookup_delivery_distance(
                    region_id,
                    city
                )

            same_existing_location = (
                existing is not None
                and int(existing["region_id"]) == region_id
                and existing["city_municipality"].strip().casefold()
                    == city.casefold()
            )

            # Legacy manually priced area:
            # keep the existing fee until distance
            # is explicitly configured.
            preserve_legacy = (
                distance is None
                and same_existing_location
                and existing["estimated_distance_km"] is None
            )

            if distance is None and not preserve_legacy:
                raise ValueError(
                    "No saved distance for this destination. "
                    "Enter its checked road-distance estimate "
                    "before saving."
                )

            if preserve_legacy:
                fee = existing["delivery_fee"]
            else:
                fee = get_delivery_fee(distance)

            enabled = int(
                request.form.get("is_enabled") == "1"
            )

            cod = int(
                enabled
                and request.form.get("cod_enabled") == "1"
            )

            if distance is not None and distance > 100:
                if enabled:
                    raise ValueError(
                        "Destinations beyond 100 km "
                        "require a manual quotation. "
                        "Uncheck Enable Delivery before saving."
                    )

                # Quotation-only areas must not
                # enter automatic checkout.
                fee = None
                cod = 0

            elif enabled and fee is None:
                raise ValueError(
                    "A confirmed delivery fee is required "
                    "before enabling delivery."
                )

            # Save the service area and its distance
            # reference in one database transaction.
            connection = mysql.connection
            cursor = connection.cursor()

            try:
                if action == "add":
                    cursor.execute(
                        """
                        INSERT INTO service_areas (
                            region_id,
                            city_municipality,
                            estimated_distance_km,
                            delivery_fee,
                            is_enabled,
                            cod_enabled
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            region_id,
                            city,
                            distance,
                            fee,
                            enabled,
                            cod
                        )
                    )

                    area_id = cursor.lastrowid

                else:
                    cursor.execute(
                        """
                        UPDATE service_areas
                        SET
                            region_id = %s,
                            city_municipality = %s,
                            estimated_distance_km = %s,
                            delivery_fee = %s,
                            is_enabled = %s,
                            cod_enabled = %s
                        WHERE id = %s
                        """,
                        (
                            region_id,
                            city,
                            distance,
                            fee,
                            enabled,
                            cod,
                            area_id
                        )
                    )

                if distance is not None:
                    cursor.execute(
                        """
                        INSERT INTO delivery_route_distances (
                            region_id,
                            city_municipality,
                            distance_km
                        )
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            distance_km = VALUES(distance_km)
                        """,
                        (
                            region_id,
                            city,
                            distance
                        )
                    )

                connection.commit()

            except Exception:
                connection.rollback()
                raise

            finally:
                cursor.close()

            try:
                audit(
                    "delivery_area_saved",
                    "service_areas",
                    area_id,
                    (
                        f"{city}, {region['name']}; "
                        f"km={distance}; fee={fee}; "
                        f"enabled={enabled}; cod={cod}"
                    )
                )

            except Exception:
                current_app.logger.exception(
                    "Delivery area saved, but audit logging failed."
                )

            if fee is None:
                message = (
                    "Delivery area saved as quotation-only. "
                    "Automatic delivery is disabled."
                )
            else:
                message = (
                    "Delivery area saved successfully. "
                    f"Fee: PHP {Decimal(str(fee)):.2f}"
                )

            flash(message, "success")

        except ValueError as exc:
            flash(str(exc), "danger")

        except IntegrityError:
            flash(
                "Could not save this area because "
                "a matching record already exists.",
                "danger"
            )

        except Exception:
            current_app.logger.exception(
                "Delivery area save failed."
            )

            flash(
                "Database error while saving the area. "
                "Verify that the Delivery Area SQL "
                "migration was executed.",
                "danger"
            )

        return redirect(
            url_for("admin.admin_delivery_areas")
        )

    # ======================================
    # GET - LIST AREAS
    # ======================================

    regions = db_all(
        """
        SELECT id, name
        FROM service_regions
        WHERE is_active = 1
        ORDER BY name
        """
    )

    total = db_one(
        """
        SELECT COUNT(*) AS n
        FROM service_areas
        """
    )["n"]

    page, pages, offset = get_page_info(total)

    rows = db_all(
        """
        SELECT
            a.*,
            r.name AS region_name
        FROM service_areas a
        JOIN service_regions r
            ON r.id = a.region_id
        ORDER BY
            r.name,
            a.city_municipality,
            a.id
        LIMIT %s OFFSET %s
        """,
        (ADMIN_PAGE_SIZE, offset)
    )

    return console(
        "areas",
        "Delivery Areas",
        rows=rows,
        regions=regions,
        page=page,
        pages=pages,
        total=total
    )

# ==========================================
# STORE PICKUP SETTINGS
# ==========================================

@admin_bp.route(
    "/pickup-settings",
    methods=["GET", "POST"]
)
@role_required("admin")
def admin_pickup_settings():

    settings = db_one(
        """
        SELECT
            id,
            deposit_percent,
            pickup_enabled
        FROM store_pickup_settings
        WHERE id = 1
        """
    )

    if not settings:
        flash(
            "Store Pickup settings are missing. "
            "Run the database migration first.",
            "danger"
        )
        return redirect(
            url_for("admin.dashboard")
        )

    if request.method == "POST":

        raw = request.form.get(
            "deposit_percent", ""
        ).strip()

        try:
            percent = Decimal(raw)

            if (
                not percent.is_finite()
                or percent < Decimal("1.00")
                or percent > Decimal("100.00")
                or percent.as_tuple().exponent < -2
            ):
                raise ValueError

        except (InvalidOperation, ValueError):
            flash(
                "Enter a deposit percentage "
                "between 1% and 100%, with "
                "up to two decimal places.",
                "danger"
            )
            return redirect(
                url_for("admin.admin_pickup_settings")
            )

        try:
            db_write(
                """
                UPDATE store_pickup_settings
                SET deposit_percent = %s
                WHERE id = 1
                """,
                (percent,)
            )

            audit(
                "pickup_deposit_updated",
                "store_pickup_settings",
                1,
                (
                    f"Deposit changed from "
                    f"{settings['deposit_percent']}% "
                    f"to {percent}%"
                )
            )

            flash(
                "Store Pickup deposit percentage "
                "updated successfully.",
                "success"
            )

        except Exception:
            current_app.logger.exception(
                "Could not update pickup deposit."
            )

            flash(
                "Unable to save the pickup settings.",
                "danger"
            )

        return redirect(
            url_for("admin.admin_pickup_settings")
        )

    return console(
        "pickup_settings",
        "Store Pickup Settings",
        settings=settings
    )

# ==========================================
# INVENTORY OVERVIEW + MOVEMENT HISTORY
# ==========================================

@admin_bp.route("/stock-control")
@role_required("admin")
def admin_inventory():

    per_page = 10

    q = request.args.get(
        "q", ""
    ).strip()[:80]

    status = request.args.get(
        "status", "active"
    ).strip().lower()

    if status not in ("active", "archived"):
        status = "active"

    where = "i.is_active = %s"
    params = [1 if status == "active" else 0]

    if q:
        where += (
            " AND ("
            "i.item_name LIKE %s "
            "OR i.sku LIKE %s"
            ")"
        )

        keyword = f"%{q}%"
        params.extend([keyword, keyword])

    total = int(db_one(
        f"""
        SELECT COUNT(*) AS n
        FROM inventory_items i
        WHERE {where}
        """,
        tuple(params)
    )["n"])

    pages = max(
        1,
        (total + per_page - 1) // per_page
    )

    page = min(page_number(), pages)
    offset = (page - 1) * per_page

    rows = db_all(
        f"""
        SELECT
            i.*,
            c.name AS category_name
        FROM inventory_items i
        JOIN inventory_categories c
            ON c.id = i.category_id
        WHERE {where}
        ORDER BY i.item_name, i.id
        LIMIT %s OFFSET %s
        """,
        tuple(params + [per_page, offset])
    )

    categories = db_all(
        """
        SELECT id, name
        FROM inventory_categories
        ORDER BY name, id
        """
    )

    movement_total = int(db_one(
        """
        SELECT COUNT(*) AS n
        FROM stock_movements
        """
    )["n"])

    movement_pages = max(
        1,
        (movement_total + per_page - 1)
        // per_page
    )

    requested_movement_page = request.args.get(
        "mov_page", default=1, type=int
    )

    movement_page = min(
        max(1, requested_movement_page or 1),
        movement_pages
    )

    movement_offset = (
        movement_page - 1
    ) * per_page

    movements = db_all(
        """
        SELECT
            m.id,
            m.inventory_item_id,
            i.item_name,
            i.unit,
            m.movement_type,
            m.quantity_change,
            m.quantity_before,
            m.quantity_after,
            m.notes
        FROM stock_movements m
        JOIN inventory_items i
            ON i.id = m.inventory_item_id
        ORDER BY m.id DESC
        LIMIT %s OFFSET %s
        """,
        (per_page, movement_offset)
    )

    return console(
        "inventory",
        "Inventory",
        rows=rows,
        categories=categories,
        q=q,
        status=status,
        page=page,
        pages=pages,
        total=total,
        movements=movements,
        movement_page=movement_page,
        movement_pages=movement_pages,
        movement_total=movement_total,
    )

# ADD INVENTORY ITEM

# ==========================================
# ADD INVENTORY ITEM WITH OPENING STOCK
# ==========================================

@admin_bp.route(
    "/stock-control/add",
    methods=["POST"]
)
@role_required("admin")
def admin_inventory_add():

    try:
        name = request.form.get(
            "item_name", ""
        ).strip()

        category_id = request.form.get(
            "category_id", type=int
        )

        item_type = request.form.get(
            "item_type", ""
        ).strip()

        unit = request.form.get(
            "unit", ""
        ).strip()

        sku = request.form.get(
            "sku", ""
        ).strip() or None

        reorder = quantity(
            request.form.get("reorder_level") or "0",
            allow_zero=True
        )

        opening_stock = quantity(
            request.form.get("opening_stock") or "0",
            allow_zero=True
        )

        # Basic validation
        if not (2 <= len(name) <= 180):
            raise ValueError(
                "Item name must contain 2 to 180 characters."
            )

        if not (1 <= len(unit) <= 20):
            raise ValueError(
                "Enter a valid measurement unit."
            )

        if sku and len(sku) > 50:
            raise ValueError(
                "SKU must be 50 characters or fewer."
            )

        if item_type not in (
            "ingredient",
            "packaging",
            "finished_product"
        ):
            raise ValueError(
                "Select a valid inventory item type."
            )

        category = db_one(
            """
            SELECT id
            FROM inventory_categories
            WHERE id = %s
            """,
            (category_id,)
        ) if category_id else None

        if not category:
            raise ValueError(
                "Select a valid inventory category."
            )

    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(
            url_for("admin.admin_inventory")
        )

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        # Check for duplicate SKU
        if sku:
            cur.execute(
                """
                SELECT id
                FROM inventory_items
                WHERE sku = %s
                LIMIT 1
                """,
                (sku,)
            )

            if cur.fetchone():
                raise ValueError(
                    "This SKU is already being used."
                )

        # Create inventory item
        cur.execute(
            """
            INSERT INTO inventory_items
            (
                category_id,
                item_type,
                item_name,
                sku,
                unit,
                quantity_on_hand,
                reorder_level
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                category_id,
                item_type,
                name,
                sku,
                unit,
                opening_stock,
                reorder
            )
        )

        item_id = cur.lastrowid

        # Record opening stock in movement history
        if opening_stock > 0:
            cur.execute(
                """
                INSERT INTO stock_movements
                (
                    inventory_item_id,
                    movement_type,
                    quantity_change,
                    quantity_before,
                    quantity_after,
                    notes,
                    recorded_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item_id,
                    "stock_in",
                    opening_stock,
                    Decimal("0"),
                    opening_stock,
                    "Initial inventory opening stock",
                    actor_id()
                )
            )

        # Record audit trail
        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "inventory_item_created",
                "inventory_items",
                item_id,
                (
                    f"Created {name}; "
                    f"opening stock={opening_stock} {unit}; "
                    f"reorder level={reorder} {unit}"
                )
            )
        )

        conn.commit()

        flash(
            "Inventory item created successfully "
            "with its opening stock.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except IntegrityError:
        conn.rollback()
        flash(
            "Could not create inventory item. "
            "Check for a duplicate SKU or invalid data.",
            "danger"
        )

    except Exception:
        conn.rollback()

        current_app.logger.exception(
            "Failed to create inventory item"
        )

        flash(
            "Unable to create inventory item. "
            "Please check the server logs.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for("admin.admin_inventory")
    )

# EDIT INVENTORY ITEM

@admin_bp.route(
    "/stock-control/<int:item_id>/edit",
    methods=["POST"]
)
@role_required("admin")
def admin_inventory_edit(item_id):

    # Only active items can be edited.
    existing = db_one(
        """
        SELECT id, item_type, unit
        FROM inventory_items
        WHERE id = %s
          AND is_active = 1
        """,
        (item_id,)
    )

    if not existing:
        abort(404)

    try:

        # ----------------------------------
        # GET FORM VALUES
        # ----------------------------------

        name = request.form.get(
            "item_name", ""
        ).strip()

        category_id = request.form.get(
            "category_id", type=int
        )

        sku = request.form.get(
            "sku", ""
        ).strip() or None

        reorder = quantity(
            request.form.get(
                "reorder_level", "0"
            ),
            allow_zero=True
        )

        # ----------------------------------
        # VALIDATION
        # ----------------------------------

        if not 2 <= len(name) <= 180:
            raise ValueError(
                "Item name must contain "
                "2 to 180 characters."
            )

        if sku and len(sku) > 50:
            raise ValueError(
                "SKU must be 50 characters or fewer."
            )

        if not category_id:
            raise ValueError(
                "Please select an inventory category."
            )

        category = db_one(
            """
            SELECT id
            FROM inventory_categories
            WHERE id = %s
            """,
            (category_id,)
        )

        if not category:
            raise ValueError(
                "Selected inventory category "
                "does not exist."
            )

        # Prevent changing units and item types
        # while stock and recipes use this item.

        # ----------------------------------
        # UPDATE DATABASE
        # ----------------------------------

        db_write(
            """
            UPDATE inventory_items

            SET
                item_name = %s,
                category_id = %s,
                sku = %s,
                reorder_level = %s

            WHERE id = %s
              AND is_active = 1
            """,
            (
                name,
                category_id,
                sku,
                reorder,
                item_id
            )
        )

        audit(
            "inventory_item_updated",
            "inventory_items",
            item_id,
            f"Updated item: {name}"
        )

        flash(
            "Inventory item updated successfully.",
            "success"
        )

    
    except IntegrityError:
        flash(
            "This SKU is already being used "
            "by another inventory item.",
            "danger"
        )

    except ValueError as exc:
        flash(str(exc), "danger")

    except Exception:
        current_app.logger.exception(
            "Inventory item edit failed: item_id=%s",
            item_id
        )

        flash(
            "Could not save inventory changes. "
            "Please check the Flask terminal.",
            "danger"
        )

    return redirect(
        url_for("admin.admin_inventory")
    )


# ==========================================
# ARCHIVE INVENTORY ITEM
# ==========================================

@admin_bp.post(
    "/stock-control/<int:item_id>/archive"
)
@role_required("admin")
def admin_inventory_archive(item_id):

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id, item_name, is_active
            FROM inventory_items
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,)
        )

        item = cur.fetchone()

        if not item:
            raise ValueError(
                "Inventory item not found."
            )

        if not item["is_active"]:
            raise ValueError(
                "This item is already archived."
            )

        cur.execute(
            """
            UPDATE inventory_items
            SET is_active = 0
            WHERE id = %s
            """,
            (item_id,)
        )

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "inventory_item_archived",
                "inventory_items",
                item_id,
                f"Archived inventory item: {item['item_name']}"
            )
        )

        conn.commit()

        flash(
            "Inventory item archived successfully.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()

        current_app.logger.exception(
            "Inventory archive failed"
        )

        flash(
            "Unable to archive inventory item.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for("admin.admin_inventory")
    )


# ==========================================
# RESTORE INVENTORY ITEM
# ==========================================

@admin_bp.post(
    "/stock-control/<int:item_id>/restore"
)
@role_required("admin")
def admin_inventory_restore(item_id):

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id, item_name, is_active
            FROM inventory_items
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,)
        )

        item = cur.fetchone()

        if not item:
            raise ValueError(
                "Inventory item not found."
            )

        if item["is_active"]:
            raise ValueError(
                "This item is already active."
            )

        cur.execute(
            """
            UPDATE inventory_items
            SET is_active = 1
            WHERE id = %s
            """,
            (item_id,)
        )

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "inventory_item_restored",
                "inventory_items",
                item_id,
                f"Restored inventory item: {item['item_name']}"
            )
        )

        conn.commit()

        flash(
            "Inventory item restored successfully.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()

        current_app.logger.exception(
            "Inventory restore failed"
        )

        flash(
            "Unable to restore inventory item.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_inventory",
            status="archived"
        )
    )


# ==========================================
# REMOVE UNUSED INVENTORY ITEM
# ==========================================

@admin_bp.post(
    "/stock-control/<int:item_id>/remove"
)
@role_required("admin")
def admin_inventory_remove(item_id):

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT
                id,
                item_name,
                quantity_on_hand,
                is_active
            FROM inventory_items
            WHERE id = %s
            FOR UPDATE
            """,
            (item_id,)
        )

        item = cur.fetchone()

        if not item:
            raise ValueError(
                "Inventory item not found."
            )

        if item["is_active"]:
            raise ValueError(
                "Archive the item before removing it."
            )

        if Decimal(str(item["quantity_on_hand"])) != 0:
            raise ValueError(
                "Items with remaining stock cannot "
                "be permanently removed."
            )

        # Protect existing production recipes.
        cur.execute(
            """
            SELECT id
            FROM recipe_ingredients
            WHERE inventory_item_id = %s
            LIMIT 1
            """,
            (item_id,)
        )

        if cur.fetchone():
            raise ValueError(
                "This item is used in a recipe. "
                "It can be archived but not removed."
            )

        # Protect historical inventory records.
        cur.execute(
            """
            SELECT id
            FROM stock_movements
            WHERE inventory_item_id = %s
            LIMIT 1
            """,
            (item_id,)
        )

        if cur.fetchone():
            raise ValueError(
                "This item has stock movement history. "
                "Keep it archived instead."
            )

        # Audit before deletion.
        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "inventory_item_removed",
                "inventory_items",
                item_id,
                f"Removed unused item: {item['item_name']}"
            )
        )

        cur.execute(
            """
            DELETE FROM inventory_items
            WHERE id = %s
              AND is_active = 0
            """,
            (item_id,)
        )

        if cur.rowcount != 1:
            raise ValueError(
                "Inventory item could not be removed."
            )

        conn.commit()

        flash(
            "Unused inventory item removed successfully.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except IntegrityError:
        conn.rollback()

        flash(
            "This item is referenced by another record. "
            "Keep it archived instead.",
            "danger"
        )

    except Exception:
        conn.rollback()

        current_app.logger.exception(
            "Inventory removal failed"
        )

        flash(
            "Unable to remove inventory item.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for(
            "admin.admin_inventory",
            status="archived"
        )
    )

# RECORD STOCK MOVEMENT

@admin_bp.route(
    "/stock-control/<int:item_id>/movement",
    methods=["POST"]
)
@role_required("admin")
def admin_inventory_movement(item_id):

    mode = request.form.get(
        "movement_type", ""
    )

    try:
        if mode not in ("stock_in", "stock_out"):
            raise ValueError(
                "Choose stock-in or stock-out."
            )

        qty = quantity(
            request.form.get(
                "quantity_change", ""
            )
        )

        notes = request.form.get(
            "notes", ""
        ).strip()

        if not 3 <= len(notes) <= 255:
            raise ValueError(
                "Enter a reason containing "
                "3 to 255 characters."
            )

    except ValueError as exc:
        flash(str(exc), "danger")

        return redirect(
            url_for("admin.admin_inventory")
        )

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        cur.execute(
            """
            SELECT id, item_name, quantity_on_hand
            FROM inventory_items
            WHERE id = %s
              AND is_active = 1
            FOR UPDATE
            """,
            (item_id,),
        )

        row = cur.fetchone()

        if not row:
            raise ValueError(
                "Inventory item not found."
            )

        before = Decimal(
            row["quantity_on_hand"]
        )

        signed = (
            qty if mode == "stock_in"
            else -qty
        )

        after = before + signed

        if after < 0:
            raise ValueError(
                "Stock-out exceeds available quantity."
            )

        cur.execute(
            """
            UPDATE inventory_items
            SET quantity_on_hand = %s
            WHERE id = %s
            """,
            (after, item_id),
        )

        cur.execute(
            """
            INSERT INTO stock_movements
            (
                inventory_item_id,
                movement_type,
                quantity_change,
                quantity_before,
                quantity_after,
                notes,
                recorded_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                item_id,
                mode,
                signed,
                before,
                after,
                notes,
                actor_id(),
            ),
        )

        cur.execute(
            """
            INSERT INTO audit_logs
            (
                user_id,
                action,
                entity_name,
                entity_id,
                details
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                actor_id(),
                "stock_adjusted",
                "inventory_items",
                item_id,
                f"{mode}: {signed}; {notes}",
            ),
        )

        conn.commit()

        flash(
            "Stock movement recorded.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()

        current_app.logger.exception(
            "Stock movement failed"
        )

        flash(
            "Could not record stock movement.",
            "danger"
        )

    finally:
        cur.close()

    return redirect(
        url_for("admin.admin_inventory")
    )

# SALES INSIGHTS

@admin_bp.route("/insights")
@role_required("admin")
def admin_insights():

    overview = db_one(
        """
        SELECT
            COUNT(*) AS total_orders,
            SUM(
                status IN (
                    'pending',
                    'pending_verification'
                )
            ) AS awaiting,
            SUM(
                status = 'completed'
            ) AS completed,
            COALESCE(
                SUM(
                    CASE
                        WHEN status = 'completed'
                        THEN total_amount
                        ELSE 0
                    END
                ), 0
            ) AS completed_value
        FROM orders
        """
    )

    top = db_all(
        """
        SELECT
            oi.product_name_snapshot AS name,
            SUM(oi.quantity) AS units,
            SUM(oi.line_total) AS amount
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status = 'completed'
        GROUP BY oi.product_name_snapshot
        ORDER BY units DESC
        LIMIT 6
        """
    )

    recent = db_all(
        """
        SELECT
            DATE(created_at) AS order_day,
            COUNT(*) AS orders,
            SUM(total_amount) AS value
        FROM orders
        WHERE created_at >= DATE_SUB(
            CURDATE(), INTERVAL 7 DAY
        )
        GROUP BY DATE(created_at)
        ORDER BY order_day DESC
        """
    )

    return console(
        "insights",
        "Sales Insights",
        overview=overview,
        top=top,
        recent=recent
    )

# AUDIT HISTORY

@admin_bp.route("/activity")
@role_required("admin")
def admin_activity():

    total = db_one(
        "SELECT COUNT(*) AS n FROM audit_logs"
    )["n"]

    page, pages, offset = get_page_info(total)

    rows = db_all(
        """
        SELECT
            a.created_at,
            a.action,
            a.entity_name,
            a.entity_id,
            a.details,
            CONCAT(
                COALESCE(u.first_name, ''),
                ' ',
                COALESCE(u.last_name, '')
            ) AS actor
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.user_id
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT %s OFFSET %s
        """,
        (ADMIN_PAGE_SIZE, offset),
    )

    return console(
        "activity",
        "Audit History",
        rows=rows,
        page=page,
        pages=pages,
        total=total,
    )

# CSV REPORTS

def csv_safe(value):
    s = "" if value is None else str(value)

    if s and s[0] in (
        "=", "+", "-", "@", "\t", "\r", "\n"
    ):
        s = "'" + s

    return s


@admin_bp.route(
    "/data-exports/<kind>.csv"
)
@role_required("admin")
def admin_export(kind):

    configs = {
        "products": (
            """
            SELECT
                p.id,
                p.name,
                c.name AS category,
                p.price,
                p.is_active,
                p.is_available
            FROM products p
            JOIN product_categories c
                ON c.id = p.category_id
            ORDER BY p.id
            LIMIT 10000
            """,
            (
                "ID", "Product", "Category",
                "Price", "Active", "Available"
            ),
        ),

        "orders": (
            """
            SELECT
                order_number,
                created_at,
                status,
                order_type,
                payment_method,
                subtotal,
                delivery_fee,
                total_amount
            FROM orders
            ORDER BY created_at DESC
            LIMIT 10000
            """,
            (
                "Order Number", "Created",
                "Status", "Type", "Payment",
                "Subtotal", "Delivery Fee", "Total"
            ),
        ),

        "inventory": (
            """
            SELECT
                id,
                item_name,
                sku,
                item_type,
                unit,
                quantity_on_hand,
                reorder_level
            FROM inventory_items
            WHERE is_active = 1
            ORDER BY item_name
            LIMIT 10000
            """,
            (
                "ID", "Item", "SKU", "Type",
                "Unit", "On Hand", "Reorder Level"
            ),
        ),
    }

    if kind not in configs:
        abort(404)

    query, headers = configs[kind]

    rows = db_all(query)

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(headers)

    for row in rows:
        writer.writerow(
            [csv_safe(v) for v in row.values()]
        )

    audit(
        "report_exported",
        kind,
        details=f"rows={len(rows)}"
    )

    filename = (
        f"inventorypro_{kind}_"
        f"{datetime.now():%Y%m%d}.csv"
    )

    return Response(
        "\ufeff" + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@admin_bp.route("/data-exports")
@role_required("admin")
def admin_reports():

    return console(
        "reports",
        "Data Exports"
    )

# DASHBOARD EXTRA STATISTICS

def dashboard_extra():

    overview = db_one(
        """
        SELECT
            COUNT(*) AS total_orders,

            COALESCE(
                SUM(
                    status IN (
                        'pending',
                        'pending_verification'
                    )
                ), 0
            ) AS waiting_orders,

            COALESCE(
                SUM(status = 'completed'), 0
            ) AS completed_orders

        FROM orders
        """
    )

    customers = db_one(
        """
        SELECT COUNT(*) AS n
        FROM users
        WHERE role = 'customer'
        """
    )["n"]

    low_stock = db_all(
        """
        SELECT
            item_name,
            quantity_on_hand,
            unit
        FROM inventory_items
        WHERE is_active = 1
          AND reorder_level > 0
          AND quantity_on_hand <= reorder_level
        ORDER BY quantity_on_hand
        LIMIT 5
        """
    )

    recent_orders = db_all(
        """
        SELECT
            id,
            order_number,
            status,
            total_amount
        FROM orders
        ORDER BY created_at DESC
        LIMIT 5
        """
    )

    return (
        overview,
        customers,
        low_stock,
        recent_orders
    )
