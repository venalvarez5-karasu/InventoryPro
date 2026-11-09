
import csv
import io
import re
import unicodedata

from datetime import datetime
from decimal import Decimal, InvalidOperation

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
    "confirmed": ("preparing", "cancelled"),
    "preparing": ("ready",),
    "ready": ("out_for_delivery", "completed"),
    "out_for_delivery": ("completed",),
}


# ==========================================
# SHARED HELPERS
# ==========================================

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


# ==========================================
# CATEGORY MANAGEMENT
# ==========================================

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

    rows = db_all(
        """
        SELECT c.*,
        (
            SELECT COUNT(*)
            FROM products p
            WHERE p.category_id = c.id
        ) AS product_count
        FROM product_categories c
        ORDER BY c.display_order, c.name
        """
    )

    return console(
        "categories",
        "Product Categories",
        rows=rows
    )


# ==========================================
# ORDER MANAGEMENT
# ==========================================

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

    page = page_number()

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
        LIMIT 15 OFFSET %s
        """,
        tuple(
            params + [(page - 1) * 15]
        ),
    )

    return console(
        "orders",
        "Order Management",
        rows=rows,
        q=q,
        status=status,
        statuses=ORDER_STATUSES,
        page=page,
        pages=max(1, (total + 14) // 15),
        total=total
    )


@admin_bp.route("/orders/<int:order_id>")
@role_required("admin")
def admin_order_detail(order_id):

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

    return render_template(
        "admin_order_detail.html",
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
                "admin.admin_order_detail",
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
            "admin.admin_order_detail",
            order_id=order_id
        )
    )


# ==========================================
# MANUAL PAYMENT CONFIRMATION
# ==========================================

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
            "admin.admin_order_detail",
            order_id=order_id
        )
    )


# ==========================================
# CUSTOMER MANAGEMENT
# ==========================================

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

    page = page_number()

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
        ORDER BY created_at DESC
        LIMIT 15 OFFSET %s
        """,
        tuple(
            params + [(page - 1) * 15]
        ),
    )

    return console(
        "customers",
        "Customers",
        rows=rows,
        q=q,
        page=page,
        pages=max(1, (total + 14) // 15),
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
# DELIVERY AREA MANAGEMENT
# ==========================================

@admin_bp.route(
    "/delivery-areas",
    methods=["GET", "POST"]
)
@role_required("admin")
def admin_delivery_areas():

    if request.method == "POST":

        action = request.form.get("action", "")
        area_id = request.form.get(
            "area_id", type=int
        )

        try:
            if action not in ("add", "update"):
                raise ValueError("Invalid action.")

            region_id = request.form.get(
                "region_id", type=int
            )

            city = request.form.get(
                "city_municipality", ""
            ).strip()

            region = db_one(
                """
                SELECT id
                FROM service_regions
                WHERE id = %s
                  AND is_active = 1
                """,
                (region_id,),
            ) if region_id else None

            if not region:
                raise ValueError(
                    "Choose a valid region."
                )

            if not 2 <= len(city) <= 100:
                raise ValueError(
                    "City or municipality must "
                    "contain 2 to 100 characters."
                )

            fee_raw = request.form.get(
                "delivery_fee", ""
            ).strip()

            fee = (
                money(fee_raw)
                if fee_raw else None
            )

            enabled = int(
                request.form.get("is_enabled") == "1"
            )

            cod = int(
                enabled and
                request.form.get("cod_enabled") == "1"
            )

            if enabled and fee is None:
                raise ValueError(
                    "Enter a confirmed delivery fee "
                    "before enabling this area."
                )

            if action == "add":

                area_id = db_write(
                    """
                    INSERT INTO service_areas
                    (
                        region_id,
                        city_municipality,
                        delivery_fee,
                        is_enabled,
                        cod_enabled
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        region_id, city,
                        fee, enabled, cod
                    ),
                )

            else:
                if not area_id:
                    abort(404)

                existing = db_one(
                    """
                    SELECT id
                    FROM service_areas
                    WHERE id = %s
                    """,
                    (area_id,),
                )

                if not existing:
                    abort(404)

                db_write(
                    """
                    UPDATE service_areas
                    SET
                        region_id = %s,
                        city_municipality = %s,
                        delivery_fee = %s,
                        is_enabled = %s,
                        cod_enabled = %s
                    WHERE id = %s
                    """,
                    (
                        region_id, city,
                        fee, enabled,
                        cod, area_id
                    ),
                )

            audit(
                "delivery_area_saved",
                "service_areas",
                area_id,
                f"{city}, enabled={enabled}, cod={cod}"
            )

            flash(
                "Delivery area saved.",
                "success"
            )

        except (ValueError, IntegrityError) as exc:

            if isinstance(exc, IntegrityError):
                flash(
                    "This city is already registered "
                    "in that region.",
                    "danger"
                )
            else:
                flash(str(exc), "danger")

        return redirect(
            url_for("admin.admin_delivery_areas")
        )

    regions = db_all(
        """
        SELECT id, name
        FROM service_regions
        WHERE is_active = 1
        ORDER BY name
        """
    )

    rows = db_all(
        """
        SELECT a.*, r.name AS region_name
        FROM service_areas a
        JOIN service_regions r
            ON r.id = a.region_id
        ORDER BY r.name, a.city_municipality
        """
    )

    return console(
        "areas",
        "Delivery Areas",
        rows=rows,
        regions=regions
    )


# ==========================================
# INVENTORY OVERVIEW
# ==========================================

@admin_bp.route("/stock-control")
@role_required("admin")
def admin_inventory():

    q = request.args.get(
        "q", ""
    ).strip()[:80]

    params = []
    where = "i.is_active = 1"

    if q:
        where += (
            " AND ("
            "i.item_name LIKE %s "
            "OR i.sku LIKE %s"
            ")"
        )

        params = [f"%{q}%"] * 2

    total = db_one(
        f"""
        SELECT COUNT(*) AS n
        FROM inventory_items i
        WHERE {where}
        """,
        tuple(params),
    )["n"]

    page = page_number()

    rows = db_all(
        f"""
        SELECT
            i.*,
            c.name AS category_name
        FROM inventory_items i
        JOIN inventory_categories c
            ON c.id = i.category_id
        WHERE {where}
        ORDER BY i.item_name
        LIMIT 15 OFFSET %s
        """,
        tuple(
            params + [(page - 1) * 15]
        ),
    )

    cats = db_all(
        """
        SELECT id, name
        FROM inventory_categories
        ORDER BY name
        """
    )

    return console(
        "inventory",
        "Inventory",
        rows=rows,
        categories=cats,
        q=q,
        page=page,
        pages=max(1, (total + 14) // 15),
        total=total
    )


# ==========================================
# ADD INVENTORY ITEM
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
        )

        unit = request.form.get(
            "unit", ""
        ).strip()

        sku = request.form.get(
            "sku", ""
        ).strip() or None

        reorder = quantity(
            request.form.get(
                "reorder_level", "0"
            ),
            allow_zero=True
        )

        if not (
            2 <= len(name) <= 180
            and 1 <= len(unit) <= 20
        ):
            raise ValueError(
                "Check the item name and unit."
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
                "Select an inventory item type."
            )

        category = db_one(
            """
            SELECT id
            FROM inventory_categories
            WHERE id = %s
            """,
            (category_id,),
        ) if category_id else None

        if not category:
            raise ValueError(
                "Select an inventory category."
            )

        item_id = db_write(
            """
            INSERT INTO inventory_items
            (
                category_id,
                item_type,
                item_name,
                sku,
                unit,
                reorder_level
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                category_id,
                item_type,
                name,
                sku,
                unit,
                reorder
            ),
        )

        audit(
            "inventory_item_created",
            "inventory_items",
            item_id,
            name
        )

        flash(
            "Inventory item created. "
            "Record stock-in to set its quantity.",
            "success"
        )

    except (ValueError, IntegrityError) as exc:
        if isinstance(exc, IntegrityError):
            flash("Duplicate SKU.", "danger")
        else:
            flash(str(exc), "danger")

    return redirect(
        url_for("admin.admin_inventory")
    )


# ==========================================
# RECORD STOCK MOVEMENT
# ==========================================

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


# ==========================================
# SALES INSIGHTS
# ==========================================

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


# ==========================================
# AUDIT HISTORY
# ==========================================

@admin_bp.route("/activity")
@role_required("admin")
def admin_activity():

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
        LIMIT 75
        """
    )

    return console(
        "activity",
        "Audit History",
        rows=rows
    )


# ==========================================
# CSV REPORTS
# ==========================================

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


# ==========================================
# DASHBOARD EXTRA STATISTICS
# ==========================================

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
