
from flask import jsonify, url_for

from MyFlaskApp.auth.auth_bp import role_required
from .admin_bp import admin_bp, db_one, db_all


@admin_bp.route("/notifications.json", methods=["GET"])
@role_required("admin")
def admin_notifications():
    """
    Admin notifications from existing MySQL records.

    No new database tables required.
    Badge = pending orders + items needing restock.
    """

    pending = db_one(
        """
        SELECT COUNT(*) AS total
        FROM orders
        WHERE status IN (
            'pending',
            'pending_verification'
        )
        """
    )

    recent_orders = db_all(
        """
        SELECT
            o.id,
            o.order_number,
            o.status,
            o.created_at,
            o.recipient_name,

            TRIM(CONCAT(
                COALESCE(u.first_name, ''),
                ' ',
                COALESCE(u.last_name, '')
            )) AS customer_name,

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
            ) AS ordered_products

        FROM orders o

        LEFT JOIN users u
            ON u.id = o.user_id

        ORDER BY o.created_at DESC, o.id DESC

        LIMIT 6
        """
    )

    stock_condition = """
        is_active = 1
        AND (
            quantity_on_hand <= 0
            OR (
                reorder_level > 0
                AND quantity_on_hand <= reorder_level
            )
        )
    """

    stock_count = db_one(
        f"""
        SELECT COUNT(*) AS total
        FROM inventory_items
        WHERE {stock_condition}
        """
    )

    low_stock = db_all(
        f"""
        SELECT
            id,
            item_name,
            quantity_on_hand,
            reorder_level,
            unit

        FROM inventory_items

        WHERE {stock_condition}

        ORDER BY
            CASE
                WHEN quantity_on_hand <= 0
                THEN 0
                ELSE 1
            END,
            quantity_on_hand ASC,
            id ASC

        LIMIT 6
        """
    )

    pending_count = int(pending["total"] or 0)
    low_stock_count = int(stock_count["total"] or 0)

    orders = []

    for order in recent_orders:
        customer = (
            order["customer_name"]
            or order["recipient_name"]
            or "Customer"
        )

        placed_at = order["created_at"]

        orders.append({
            "id": order["id"],
            "number": order["order_number"],
            "customer": customer,
            "status": order["status"].replace("_", " ").title(),
            "products": (
                order["ordered_products"]
                or "View the order for item details."
            )[:180],
            "time": (
                placed_at.strftime("%b %d, %Y %I:%M %p")
                if placed_at else ""
            ),
            "url": url_for(
                "admin.admin_orderdetail",
                order_id=order["id"]
            ),
        })

    stock_items = []

    for item in low_stock:
        on_hand = item["quantity_on_hand"]
        reorder = item["reorder_level"]

        stock_items.append({
            "id": item["id"],
            "name": item["item_name"],
            "quantity": str(on_hand),
            "unit": item["unit"],
            "reorder_level": str(reorder),
            "status": (
                "Out of Stock"
                if on_hand <= 0
                else "Low Stock"
            ),
            "url": url_for("admin.admin_inventory"),
        })

    return jsonify({
        "pending_count": pending_count,
        "low_stock_count": low_stock_count,
        "attention_count": (
            pending_count + low_stock_count
        ),
        "orders": orders,
        "stock_items": stock_items,
    })
