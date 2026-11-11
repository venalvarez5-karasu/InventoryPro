from flask import (
    Blueprint,
    redirect,
    render_template,
    url_for,
    abort,
    flash,
)

from MySQLdb.cursors import DictCursor

from flask import request
from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user
import re
from decimal import Decimal



orders_bp = Blueprint(
    "orders",
    __name__,
    template_folder="templates",
)


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


@orders_bp.route("/")
def order_list():

    user_id = get_user_id()

    if not user_id:

        flash(
            "Log in to view your orders.",
            "warning"
        )

        return redirect(
            url_for(
                "auth.login",
                next=url_for("orders.order_list")
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
        ORDER BY created_at DESC
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
# CUSTOMER - SUBMIT PICKUP DEPOSIT REFERENCE
# ==========================================

@orders_bp.route(
    "/<int:order_id>/pickup-deposit",
    methods=["POST"]
)
def submit_pickup_deposit(order_id):

    user_id = get_user_id()

    if not user_id:
        return redirect(
            url_for("auth.login")
        )

    reference = request.form.get(
        "payment_reference", ""
    ).strip().upper()

    if not re.fullmatch(
        r"[A-Z0-9-]{6,100}",
        reference
    ):
        flash(
            "Enter a valid payment reference "
            "containing 6 to 100 letters, numbers "
            "or hyphens.",
            "danger"
        )

        return redirect(
            url_for(
                "orders.order_detail",
                order_id=order_id
            )
        )

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
            (order_id, user_id)
        )

        order = cur.fetchone()

        if not order:
            abort(404)

        if (
            order["order_type"] != "pickup"
            or order["status"] not in (
                "pending_verification", "pending"
            )
            or order["payment_method"] not in (
                "gcash", "bank_transfer"
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
                "The required deposit is not configured."
            )

        # Do not permit another submission while
        # a reference is being reviewed or after payment.
        cur.execute(
            """
            SELECT id, status
            FROM payments
            WHERE order_id = %s
              AND payment_purpose = 'pickup_deposit'
              AND status IN ('pending_review', 'paid')
            FOR UPDATE
            """,
            (order_id,)
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
                reference
            )
        )

        if cur.fetchone():
            raise ValueError(
                "That payment reference has already "
                "been submitted."
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
            VALUES
            (
                %s, %s, %s,
                'pending_review',
                'pickup_deposit',
                %s
            )
            """,
            (
                order_id,
                order["payment_method"],
                deposit,
                reference
            )
        )

        conn.commit()

        flash(
            "Payment reference submitted. "
            "The bakery will verify it before "
            "preparing your order.",
            "success"
        )

    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()

    return redirect(
        url_for(
            "orders.order_detail",
            order_id=order_id
        )
    )

@orders_bp.route("/<int:order_id>", methods=["GET"])
def order_detail(order_id):
    user_id = get_user_id()

    if not user_id:

        flash(
            "Log in to view your orders.",
            "warning"
        )

        return redirect(
            url_for(
                "auth.login",
                next=url_for(
                    "orders.order_detail",
                    order_id=order_id
                )
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
        (order_id,)
    )

    return render_template(
    "order_detail.html",
    order=orders[0],
    items=items,
    payments=payments,
    title="Order Details",
)