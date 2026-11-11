
import re
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user
from MyFlaskApp.production.stock_ops import (
    deduct_order_recipe_stock,
)


orders_bp = Blueprint(
    "orders",
    __name__,
    template_folder="templates",
)


# ==========================================
# DATABASE HELPERS
# ==========================================

def get_user_id():
    user = current_user()

    if isinstance(user, dict):
        return user.get("id")

    return getattr(user, "id", None)


def rows(sql, args=()):
    cur = mysql.connection.cursor(DictCursor)

    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


def detail_redirect(order_id):
    return redirect(
        url_for(
            "orders.order_detail",
            order_id=order_id,
        )
    )


# ==========================================
# CUSTOMER ORDER HISTORY
# ==========================================

@orders_bp.get("/")
def order_list():
    user_id = get_user_id()

    if not user_id:
        flash(
            "Log in to view your orders.",
            "warning",
        )
        return redirect(
            url_for(
                "auth.login",
                next=url_for("orders.order_list"),
            )
        )

    orders = rows(
        """
        SELECT
            id,
            order_number,
            status,
            order_type,
            total_amount,
            created_at
        FROM orders
        WHERE user_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 100
        """,
        (user_id,),
    )

    return render_template(
        "history.html",
        orders=orders,
        title="My Orders",
    )


# ==========================================
# ORIGINAL PICKUP DEPOSIT SUBMISSION
# ==========================================

@orders_bp.post("/<int:order_id>/pickup-deposit")
def submit_pickup_deposit(order_id):
    user_id = get_user_id()

    if not user_id:
        return redirect(url_for("auth.login"))

    reference = request.form.get(
        "payment_reference", ""
    ).strip().upper()

    if not re.fullmatch(
        r"[A-Z0-9-]{6,100}",
        reference,
    ):
        flash(
            "Enter a valid payment reference "
            "containing 6 to 100 letters, "
            "numbers or hyphens.",
            "danger",
        )
        return detail_redirect(order_id)

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
              AND user_id = %s
            FOR UPDATE
            """,
            (order_id, user_id),
        )

        order = cur.fetchone()

        if not order:
            abort(404)

        if (
            order["order_type"] != "pickup"
            or order["status"] not in (
                "pending_verification",
                "pending",
            )
            or order["payment_method"] not in (
                "gcash",
                "bank_transfer",
            )
        ):
            raise ValueError(
                "This order does not accept "
                "a pickup deposit submission."
            )

        deposit = Decimal(
            str(order["pickup_deposit_due"] or 0)
        ).quantize(Decimal("0.01"))

        if deposit <= 0:
            raise ValueError(
                "The required deposit is "
                "not configured."
            )

        cur.execute(
            """
            SELECT id, status
            FROM payments
            WHERE order_id = %s
              AND payment_purpose = 'pickup_deposit'
              AND status IN (
                  'pending_review',
                  'paid'
              )
            FOR UPDATE
            """,
            (order_id,),
        )

        if cur.fetchone():
            raise ValueError(
                "A deposit is already under review "
                "or has been verified."
            )

        cur.execute(
            """
            SELECT id
            FROM payments
            WHERE payment_method = %s
              AND payment_reference = %s
            LIMIT 1
            """,
            (
                order["payment_method"],
                reference,
            ),
        )

        if cur.fetchone():
            raise ValueError(
                "That payment reference "
                "has already been submitted."
            )

        cur.execute(
            """
            INSERT INTO payments
            (
                order_id,
                payment_method,
                amount,
                status,
                payment_purpose,
                payment_reference
            )
            VALUES (
                %s, %s, %s,
                'pending_review',
                'pickup_deposit', %s
            )
            """,
            (
                order_id,
                order["payment_method"],
                deposit,
                reference,
            ),
        )

        conn.commit()

        flash(
            "Payment reference submitted. "
            "The bakery will verify it before "
            "preparing your order.",
            "success",
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Pickup deposit submission failed"
        )
        flash(
            "Unable to submit payment reference.",
            "danger",
        )

    finally:
        cur.close()

    return detail_redirect(order_id)


# ==========================================
# MOCK GCASH PAYMENT
# LOCAL DEMONSTRATION ONLY
# ==========================================

@orders_bp.post("/<int:order_id>/mock-gcash")
def mock_gcash_payment(order_id):
    # IMPORTANT:
    # This route does not send, receive, or
    # verify any actual GCash transaction.
    #
    # It is deliberately disabled outside
    # Flask debug mode.

    if not current_app.debug:
        abort(404)

    user_id = get_user_id()

    if not user_id:
        return redirect(url_for("auth.login"))

    raw_reference = request.form.get(
        "payment_reference", ""
    ).strip().upper()

    if not re.fullmatch(
        r"[A-Z0-9-]{6,40}",
        raw_reference,
    ):
        flash(
            "Enter a demo reference containing "
            "6 to 40 letters, numbers, "
            "or hyphens.",
            "danger",
        )
        return detail_redirect(order_id)

    # Prefix clearly distinguishes simulated
    # payments from real GCash references.
    reference = "DEMO-" + raw_reference

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:
        conn.begin()

        # Lock customer's order.
        cur.execute(
            """
            SELECT
                id,
                order_number,
                user_id,
                order_type,
                payment_method,
                status,
                total_amount,
                pickup_deposit_due
            FROM orders
            WHERE id = %s
              AND user_id = %s
            FOR UPDATE
            """,
            (order_id, user_id),
        )

        order = cur.fetchone()

        if not order:
            raise ValueError(
                "Order not found or access denied."
            )

        if order["payment_method"] != "gcash":
            raise ValueError(
                "Mock payment is available "
                "only for GCash orders."
            )

        if order["status"] not in (
            "pending_verification",
            "pending",
        ):
            raise ValueError(
                "This order has already moved "
                "past the payment stage."
            )

        # A reference can be used only once.
        cur.execute(
            """
            SELECT id
            FROM payments
            WHERE payment_reference = %s
            LIMIT 1
            """,
            (reference,),
        )

        if cur.fetchone():
            raise ValueError(
                "This demo reference was already used. "
                "Enter a different reference."
            )

        # Check existing payments before
        # applying the mock transaction.
        cur.execute(
            """
            SELECT
                id,
                payment_method,
                payment_purpose,
                status,
                amount
            FROM payments
            WHERE order_id = %s
            FOR UPDATE
            """,
            (order_id,),
        )

        existing = cur.fetchall()

        if any(
            p["status"] in (
                "paid",
                "pending_review",
            )
            for p in existing
        ):
            raise ValueError(
                "This order already has a paid "
                "or pending-review payment."
            )

        if order["order_type"] == "delivery":
            amount = Decimal(
                str(order["total_amount"] or 0)
            ).quantize(Decimal("0.01"))

            unpaid = next(
                (
                    p for p in existing
                    if p["payment_method"] == "gcash"
                    and p["status"] == "unpaid"
                ),
                None,
            )

            if amount <= 0:
                raise ValueError(
                    "Invalid order payment amount."
                )

            if unpaid:
                cur.execute(
                    """
                    UPDATE payments
                    SET
                        status = 'paid',
                        payment_reference = %s,
                        paid_at = NOW()
                    WHERE id = %s
                      AND status = 'unpaid'
                    """,
                    (reference, unpaid["id"]),
                )

                if cur.rowcount != 1:
                    raise ValueError(
                        "Payment changed. "
                        "Please refresh the page."
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
                        payment_reference,
                        paid_at
                    )
                    VALUES (
                        %s, 'gcash', %s,
                        'paid', %s, NOW()
                    )
                    """,
                    (
                        order_id,
                        amount,
                        reference,
                    ),
                )

        elif order["order_type"] == "pickup":
            # Pickup payment is the deposit only.
            # Remaining balance stays due at pickup.
            amount = Decimal(
                str(
                    order["pickup_deposit_due"] or 0
                )
            ).quantize(Decimal("0.01"))

            if amount <= 0:
                raise ValueError(
                    "Pickup deposit is not configured."
                )

            cur.execute(
                """
                INSERT INTO payments
                (
                    order_id,
                    payment_method,
                    amount,
                    status,
                    payment_purpose,
                    payment_reference,
                    paid_at
                )
                VALUES (
                    %s,
                    'gcash',
                    %s,
                    'paid',
                    'pickup_deposit',
                    %s,
                    NOW()
                )
                """,
                (
                    order_id,
                    amount,
                    reference,
                ),
            )

        else:
            raise ValueError(
                "Unsupported order type."
            )

        # Reuse the EXISTING inventory logic.
        # Same recipe deduction normally used
        # by the bakery staff on confirmation.
        #
        # If stock or recipe validation fails,
        # the entire transaction rolls back.
        deduct_order_recipe_stock(
            cur=cur,
            order_id=order_id,
            actor_id=user_id,
        )

        # Automatically confirm the order.
        cur.execute(
            """
            UPDATE orders
            SET status = 'confirmed'
            WHERE id = %s
              AND status IN (
                  'pending_verification',
                  'pending'
              )
            """,
            (order_id,),
        )

        if cur.rowcount != 1:
            raise ValueError(
                "Order status changed. "
                "Please refresh."
            )

        # Distinct demo audit record.
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
            VALUES (
                %s,
                'mock_gcash_payment',
                'orders',
                %s,
                %s
            )
            """,
            (
                user_id,
                order_id,
                (
                    "DEMO ONLY - No actual money "
                    "received. Simulated GCash "
                    f"reference {reference}; "
                    "order automatically confirmed "
                    "with recipe stock deduction."
                ),
            ),
        )

        conn.commit()

        flash(
            "DEMO PAYMENT SUCCESSFUL. "
            "No real GCash payment was made. "
            "Your order is now Confirmed.",
            "success",
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        current_app.logger.exception(
            "Mock GCash payment failed"
        )
        flash(
            "Mock payment failed. "
            "Check the recipe, inventory stock, "
            "or payment record.",
            "danger",
        )

    finally:
        cur.close()

    return detail_redirect(order_id)


# ==========================================
# CUSTOMER ORDER DETAILS
# ==========================================

@orders_bp.get("/<int:order_id>")
def order_detail(order_id):
    user_id = get_user_id()

    if not user_id:
        flash(
            "Log in to view your orders.",
            "warning",
        )
        return redirect(
            url_for(
                "auth.login",
                next=url_for(
                    "orders.order_detail",
                    order_id=order_id,
                ),
            )
        )

    orders = rows(
        """
        SELECT *
        FROM orders
        WHERE id = %s
          AND user_id = %s
        """,
        (order_id, user_id),
    )

    if not orders:
        abort(404)

    items = rows(
        """
        SELECT
            product_name_snapshot,
            quantity,
            unit_price,
            line_total
        FROM order_items
        WHERE order_id = %s
        ORDER BY id
        """,
        (order_id,),
    )

    payments = rows(
        """
        SELECT
            id,
            payment_purpose,
            payment_method,
            payment_reference,
            amount,
            status
        FROM payments
        WHERE order_id = %s
        ORDER BY created_at DESC, id DESC
        """,
        (order_id,),
    )

    return render_template(
        "order_detail.html",
        order=orders[0],
        items=items,
        payments=payments,
        title="Order Details",
    )
