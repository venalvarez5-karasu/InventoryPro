
import re
from decimal import Decimal

from flask import (
    jsonify,
    request,
    redirect,
    url_for,
    flash,
    abort,
)

from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import (
    role_required,
    current_user,
)

from .admin_bp import (
    admin_bp,
    db_one,
    db_all,
)


STOCK_CONDITION = """
    i.is_active = 1
    AND (
        i.quantity_on_hand <= 0
        OR (
            i.reorder_level > 0
            AND i.quantity_on_hand <= i.reorder_level
        )
    )
"""


# ADMIN NOTIFICATION FEED

@admin_bp.route(
    "/notifications.json",
    methods=["GET"]
)
@role_required("admin")
def admin_notifications():

    admin_id = current_user()["id"]

    pending = db_one(
        """
        SELECT COUNT(*) AS total
        FROM orders o
        WHERE o.status IN (
            'pending',
            'pending_verification'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM admin_notification_reads nr
            WHERE nr.admin_user_id = %s
              AND nr.notification_key =
                  CONCAT('order:', o.id)
        )
        """,
        (admin_id,),
    )

    low_stock = db_one(
        f"""
        SELECT COUNT(*) AS total
        FROM inventory_items i
        WHERE {STOCK_CONDITION}
        AND NOT EXISTS (
            SELECT 1
            FROM admin_notification_reads nr
            WHERE nr.admin_user_id = %s
              AND nr.notification_key = CONCAT(
                  'stock:',
                  i.id,
                  ':',
                  i.quantity_on_hand
              )
        )
        """,
        (admin_id,),
    )

    recent_orders = db_all(
        """
        SELECT
            o.id,
            o.order_number,
            o.status,
            o.created_at,
            o.recipient_name,

            TRIM(
                CONCAT(
                    COALESCE(u.first_name, ''),
                    ' ',
                    COALESCE(u.last_name, '')
                )
            ) AS customer_name,

            (
                SELECT GROUP_CONCAT(
                    CONCAT(
                        oi.product_name_snapshot,
                        ' x',
                        oi.quantity
                    )
                    ORDER BY oi.id
                    SEPARATOR ', '
                )
                FROM order_items oi
                WHERE oi.order_id = o.id
            ) AS ordered_products,

            (
                nr.notification_key IS NOT NULL
            ) AS is_read

        FROM orders o

        LEFT JOIN users u
            ON u.id = o.user_id

        LEFT JOIN admin_notification_reads nr
            ON nr.admin_user_id = %s
           AND nr.notification_key = CONCAT(
               'order:', o.id
           )

        ORDER BY o.created_at DESC, o.id DESC
        LIMIT 8
        """,
        (admin_id,),
    )

    stock_items = db_all(
        f"""
        SELECT
            i.id,
            i.item_name,
            i.quantity_on_hand,
            i.reorder_level,
            i.unit,

            (
                nr.notification_key IS NOT NULL
            ) AS is_read

        FROM inventory_items i

        LEFT JOIN admin_notification_reads nr
            ON nr.admin_user_id = %s
           AND nr.notification_key = CONCAT(
               'stock:',
               i.id,
               ':',
               i.quantity_on_hand
           )

        WHERE {STOCK_CONDITION}

        ORDER BY
            i.quantity_on_hand ASC,
            i.id ASC

        LIMIT 8
        """,
        (admin_id,),
    )

    orders = []

    for order in recent_orders:

        customer = (
            order["customer_name"]
            or order["recipient_name"]
            or "Customer"
        )

        created = order["created_at"]

        orders.append({
            "key": f"order:{order['id']}",
            "read": bool(order["is_read"]),
            "number": order["order_number"],
            "status": order["status"]
                .replace("_", " ")
                .title(),
            "customer": customer,
            "products": (
                order["ordered_products"]
                or "View order details."
            )[:180],
            "time": (
                created.strftime(
                    "%b %d, %Y %I:%M %p"
                )
                if created
                else ""
            ),
            "url": url_for(
                "admin.admin_orderdetail",
                order_id=order["id"]
            ),
        })

    stock = []

    for item in stock_items:

        stock.append({
            "key": (
                f"stock:{item['id']}:"
                f"{item['quantity_on_hand']}"
            ),
            "read": bool(item["is_read"]),
            "name": item["item_name"],
            "quantity": str(
                item["quantity_on_hand"]
            ),
            "unit": item["unit"],
            "reorder_level": str(
                item["reorder_level"]
            ),
            "status": (
                "Out of Stock"
                if item["quantity_on_hand"] <= 0
                else "Low Stock"
            ),
            "url": url_for(
                "admin.admin_inventory"
            ),
        })

    pending_count = int(pending["total"] or 0)
    stock_count = int(low_stock["total"] or 0)

    return jsonify({
        "pending_count": pending_count,
        "low_stock_count": stock_count,
        "attention_count": (
            pending_count + stock_count
        ),
        "orders": orders,
        "stock_items": stock,
    })


# MARK AS READ / MARK ALL AS READ

@admin_bp.route(
    "/notifications/read",
    methods=["POST"]
)
@role_required("admin")
def mark_admin_notification_read():

    data = request.get_json(silent=True) or {}
    admin_id = current_user()["id"]

    keys = []

    if data.get("all") is True:

        pending_orders = db_all(
            """
            SELECT id
            FROM orders
            WHERE status IN (
                'pending',
                'pending_verification'
            )
            """
        )

        keys.extend(
            f"order:{row['id']}"
            for row in pending_orders
        )

        stock_items = db_all(
            f"""
            SELECT
                i.id,
                i.quantity_on_hand
            FROM inventory_items i
            WHERE {STOCK_CONDITION}
            """
        )

        keys.extend(
            (
                f"stock:{row['id']}:"
                f"{row['quantity_on_hand']}"
            )
            for row in stock_items
        )

    else:

        key = data.get("key", "")

        if (
            not isinstance(key, str)
            or not re.fullmatch(
                r"(?:order:\d+|stock:\d+:\d+(?:\.\d+)?)",
                key
            )
        ):

            return jsonify({
                "error": "Invalid notification."
            }), 400

        keys = [key]

    conn = mysql.connection
    cur = conn.cursor()

    try:

        if keys:

            cur.executemany(
                """
                INSERT IGNORE INTO
                    admin_notification_reads
                (
                    admin_user_id,
                    notification_key
                )
                VALUES (%s, %s)
                """,
                [
                    (admin_id, key)
                    for key in keys
                ],
            )

        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()

    return jsonify({
        "ok": True,
        "read_count": len(keys),
    })


# REVIEW DELIVERY GCASH PAYMENT

@admin_bp.route(
    "/orders/<int:order_id>/gcash-review",
    methods=["POST"]
)
@role_required("admin")
def admin_delivery_gcash_review(order_id):

    payment_id = request.form.get(
        "payment_id",
        type=int
    )

    decision = request.form.get(
        "decision", ""
    ).strip()

    if (
        not payment_id
        or decision not in ("verify", "reject")
    ):
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
                payment_method,
                total_amount,
                status
            FROM orders
            WHERE id = %s
            FOR UPDATE
            """,
            (order_id,),
        )

        order = cur.fetchone()

        if (
            not order
            or order["order_type"] != "delivery"
            or order["payment_method"] != "gcash"
            or order["status"] not in (
                "pending_verification",
                "pending"
            )
        ):
            raise ValueError(
                "Order is not eligible for GCash review."
            )

        cur.execute(
            """
            SELECT
                id,
                amount,
                status,
                payment_reference
            FROM payments
            WHERE id = %s
              AND order_id = %s
              AND payment_method = 'gcash'
            FOR UPDATE
            """,
            (payment_id, order_id),
        )

        payment = cur.fetchone()

        if (
            not payment
            or payment["status"] != "pending_review"
            or not payment["payment_reference"]
        ):

            raise ValueError(
                "No valid pending GCash reference found."
            )

        paid_amount = Decimal(
            str(payment["amount"])
        )

        required_amount = Decimal(
            str(order["total_amount"])
        )

        if paid_amount != required_amount:
            raise ValueError(
                "GCash amount does not match the order."
            )

        if decision == "verify":

            cur.execute(
                """
                SELECT id
                FROM payments
                WHERE order_id = %s
                  AND status = 'paid'
                LIMIT 1
                """,
                (order_id,),
            )

            if cur.fetchone():
                raise ValueError(
                    "Order already has a verified payment."
                )

        new_status = (
            "paid"
            if decision == "verify"
            else "failed"
        )

        cur.execute(
            """
            UPDATE payments
            SET
                status = %s,
                verified_by = %s,
                paid_at = CASE
                    WHEN %s = 'paid'
                    THEN NOW()
                    ELSE paid_at
                END
            WHERE id = %s
            """,
            (
                new_status,
                current_user()["id"],
                new_status,
                payment_id,
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
            VALUES (%s, %s, 'payments', %s, %s)
            """,
            (
                current_user()["id"],
                "delivery_gcash_" + new_status,
                payment_id,
                f"Order #{order_id}",
            ),
        )

        conn.commit()

        flash(
            (
                "GCash payment verified."
                if new_status == "paid"
                else "GCash reference rejected."
            ),
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
            "admin.admin_orderdetail",
            order_id=order_id
        )
    )
