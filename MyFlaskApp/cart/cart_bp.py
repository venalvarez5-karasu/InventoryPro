from datetime import datetime
from decimal import Decimal
from secrets import token_hex, token_urlsafe
from flask import jsonify
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    abort,
)

from MySQLdb.cursors import DictCursor
from MySQLdb import IntegrityError

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user


cart_bp = Blueprint(
    "cart",
    __name__,
    template_folder="templates",
)

MAX_DISTINCT = 25
MAX_QUANTITY = 99

# HELPERS

def get_user_id():

    user = current_user()

    if isinstance(user, dict):
        return user.get("id")

    return getattr(user, "id", None)


def fetch_all(query, params=()):

    cur = mysql.connection.cursor(DictCursor)

    try:
        cur.execute(query, params)
        return cur.fetchall()

    finally:
        cur.close()


def normalize(text):

    return " ".join(
        str(text or "").casefold().strip().split()
    )


def same_province(address, region_name):

    region = normalize(region_name)
    province = normalize(address)

    if region == "metro manila (ncr)":

        return province in {
            "metro manila",
            "metro manila (ncr)",
            "ncr",
            "national capital region",
        }

    return province == region

# CART ITEMS

def get_lines():

    raw = session.get("shop_cart", {})

    if not isinstance(raw, dict):
        raw = {}

    items = []
    subtotal = Decimal("0.00")

    ordered = sorted(
        raw.items(),
        key=lambda item: (
            int(item[0])
            if str(item[0]).isdigit()
            else 0
        )
    )

    for raw_id, raw_qty in ordered:

        if not str(raw_id).isdigit():
            continue

        try:
            qty = int(raw_qty)
        except (TypeError, ValueError):
            continue

        if not 1 <= qty <= MAX_QUANTITY:
            continue

        found = fetch_all(
            """
            SELECT
                id,
                name,
                slug,
                price,
                image_path,
                is_active,
                is_available
            FROM products
            WHERE id = %s
            """,
            (int(raw_id),),
        )

        if not found:
            continue

        product = found[0]

        line_total = (
            Decimal(str(product["price"]))
            * qty
        )

        items.append({
            **product,
            "quantity": qty,
            "line_total": line_total,
        })

        subtotal += line_total

    return items, subtotal


# ==========================================
# CUSTOMER HEADER - MINI CART
# ==========================================

@cart_bp.app_context_processor
def inject_store_header_cart():
    """
    Makes cart preview data available to
    customer-facing templates.

    No additional route required.
    """

    if request.blueprint not in {
        "index",
        "products",
        "cart",
        "orders",
    }:
        return {}

    items, subtotal = get_lines()

    return {
        "mini_cart_items": items[:5],
        "mini_cart_count": sum(
            int(item["quantity"])
            for item in items
        ),
        "mini_cart_subtotal": subtotal,
        "mini_cart_more": max(
            0,
            len(items) - 5
        ),
    }

# APPROVED COD ADDRESSES

def approved_addresses(user_id):

    addresses = fetch_all(
        """
        SELECT
            id,
            recipient_name,
            mobile_number,
            province,
            city_municipality,
            barangay,
            street_address,
            postal_code,
            is_default
        FROM customer_addresses
        WHERE user_id = %s
        ORDER BY is_default DESC, id DESC
        """,
        (user_id,),
    )

    areas = fetch_all(
        """
        SELECT
            s.id,
            s.city_municipality,
            s.delivery_fee,
            r.name AS region_name
        FROM service_areas s
        JOIN service_regions r
            ON r.id = s.region_id
        WHERE s.is_enabled = 1
          AND s.cod_enabled = 1
          AND r.is_active = 1
          AND s.delivery_fee IS NOT NULL
        """
    )

    eligible = []

    for address in addresses:

        matched = next(
            (
                area
                for area in areas

                if (
                    normalize(area["city_municipality"])
                    == normalize(
                        address["city_municipality"]
                    )
                )

                and same_province(
                    address["province"],
                    area["region_name"]
                )
            ),
            None
        )

        if matched:

            eligible.append({
                **address,
                "delivery_fee": matched["delivery_fee"],
            })

    return addresses, eligible

# VIEW CART

@cart_bp.route("/")
def view_cart():

    items, subtotal = get_lines()

    return render_template(
        "cart.html",
        items=items,
        subtotal=subtotal,
        title="Your Cart",
    )

# ADD TO CART

@cart_bp.route("/add", methods=["POST"])
def add_to_cart():

    product_id = request.form.get(
        "product_id", type=int
    )

    qty = request.form.get(
        "quantity", default=1, type=int
    )

    if (
        not product_id
        or not 1 <= qty <= MAX_QUANTITY
    ):
        abort(400)

    product = fetch_all(
        """
        SELECT id, name
        FROM products
        WHERE id = %s
          AND is_active = 1
          AND is_available = 1
        """,
        (product_id,),
    )

    if not product:

        flash(
            "Product is currently unavailable.",
            "warning"
        )

        return redirect(
            url_for("products.browse")
        )

    cart = dict(
        session.get("shop_cart", {})
    )

    if (
        str(product_id) not in cart
        and len(cart) >= MAX_DISTINCT
    ):

        flash(
            "Cart can contain up to "
            "25 different products.",
            "warning"
        )

        return redirect(
            url_for("cart.view_cart")
        )

    cart[str(product_id)] = min(
        MAX_QUANTITY,
        int(cart.get(str(product_id), 0)) + qty
    )

    session["shop_cart"] = cart
    session.modified = True

    flash(
        "Product added to your cart.",
        "success"
    )

    return redirect(
        url_for("cart.view_cart")
    )

# UPDATE OR REMOVE CART ITEM

@cart_bp.route("/update", methods=["POST"])

def update_cart():

    product_id = request.form.get(
        "product_id", type=int
    )

    qty = request.form.get(
        "quantity", type=int
    )

    is_ajax = (
        request.headers.get("X-Requested-With")
        == "XMLHttpRequest"
    )

    if (
        not product_id
        or qty is None
        or not 0 <= qty <= MAX_QUANTITY
    ):
        if is_ajax:
            return jsonify({
                "ok": False,
                "error": "Invalid product or quantity."
            }), 400

        abort(400)

    cart = dict(
        session.get("shop_cart", {})
    )

    if qty == 0:
        cart.pop(str(product_id), None)

    elif str(product_id) in cart:
        cart[str(product_id)] = qty

    session["shop_cart"] = cart
    session.modified = True

    # Automatic updates without redirecting.
    if is_ajax:

        items, subtotal = get_lines()

        updated_item = next(
            (
                item for item in items
                if int(item["id"]) == product_id
            ),
            None
        )

        return jsonify({
            "ok": True,
            "quantity": (
                int(updated_item["quantity"])
                if updated_item else 0
            ),
            "unit_price": (
                str(updated_item["price"])
                if updated_item else "0.00"
            ),
            "line_total": (
                str(updated_item["line_total"])
                if updated_item else "0.00"
            ),
            "subtotal": str(subtotal),
            "cart_count": sum(
                int(item["quantity"])
                for item in items
            )
        })

    # Existing behavior for normal forms.
    return redirect(
        url_for("cart.view_cart")
    )


@cart_bp.route(
    "/checkout",
    methods=["GET", "POST"]
)
def checkout():

    user_id = get_user_id()

    if not user_id:

        flash(
            "Log in to place an order.",
            "warning"
        )

        return redirect(
            url_for(
                "auth.login",
                next=url_for("cart.checkout")
            )
        )

    items, subtotal = get_lines()

    if not items:

        flash(
            "Your cart is empty.",
            "warning"
        )

        return redirect(
            url_for("cart.view_cart")
        )

    addresses, eligible = approved_addresses(
        user_id
    )

    # SUBMIT ORDER

    if request.method == "POST":

        checkout_token = request.form.get(
            "checkout_token", ""
        )

        expected = session.get(
            "checkout_token"
        )

        if (
            not checkout_token
            or checkout_token != expected
        ):

            matched = fetch_all(
                """
                SELECT id
                FROM orders
                WHERE user_id = %s
                  AND checkout_token = %s
                """,
                (user_id, checkout_token),
            ) if checkout_token else []

            if matched:

                return redirect(
                    url_for(
                        "orders.order_detail",
                        order_id=matched[0]["id"]
                    )
                )

            flash(
                "Checkout expired. Review and try again.",
                "warning"
            )

            return redirect(
                url_for("cart.checkout")
            )

        address_id = request.form.get(
            "address_id", type=int
        )

        note = request.form.get(
            "customer_note", ""
        ).strip()

        if len(note) > 500:

            flash(
                "Order note must be "
                "500 characters or fewer.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        if not any(
            address["id"] == address_id
            for address in eligible
        ):

            flash(
                "Select an address inside "
                "an enabled COD service area.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        conn = mysql.connection
        cur = conn.cursor(DictCursor)

        try:
            conn.begin()

            # Validate address ownership.
            cur.execute(
                """
                SELECT *
                FROM customer_addresses
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
                """,
                (address_id, user_id),
            )

            address = cur.fetchone()

            if not address:
                raise ValueError(
                    "Your selected address "
                    "no longer exists."
                )

            # Recheck delivery configuration.
            cur.execute(
                """
                SELECT
                    s.id,
                    s.city_municipality,
                    s.delivery_fee,
                    r.name AS region_name

                FROM service_areas s

                JOIN service_regions r
                    ON r.id = s.region_id

                WHERE s.is_enabled = 1
                  AND s.cod_enabled = 1
                  AND s.delivery_fee IS NOT NULL
                  AND r.is_active = 1

                FOR UPDATE
                """
            )

            matches = [
                area for area in cur.fetchall()

                if (
                    normalize(area["city_municipality"])
                    == normalize(
                        address["city_municipality"]
                    )
                )

                and same_province(
                    address["province"],
                    area["region_name"]
                )
            ]

            if not matches:
                raise ValueError(
                    "Delivery or COD is not enabled "
                    "for this saved address."
                )

            area = matches[0]

            # Recheck actual product prices
            # and availability on the server.
            confirmed_items = []

            final_subtotal = Decimal("0.00")

            for line in sorted(
                items,
                key=lambda item: item["id"]
            ):

                cur.execute(
                    """
                    SELECT
                        id,
                        name,
                        price,
                        is_active,
                        is_available
                    FROM products
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (line["id"],),
                )

                product = cur.fetchone()

                if (
                    not product
                    or not product["is_active"]
                    or not product["is_available"]
                ):

                    raise ValueError(
                        f"{line['name']} is no longer "
                        "available. Update your cart."
                    )

                price = Decimal(
                    str(product["price"])
                )

                qty = line["quantity"]
                line_total = price * qty

                confirmed_items.append(
                    (
                        product,
                        qty,
                        price,
                        line_total,
                    )
                )

                final_subtotal += line_total

            delivery_fee = Decimal(
                str(area["delivery_fee"])
            )

            total = (
                final_subtotal + delivery_fee
            )

            snapshot = ", ".join(
                filter(
                    None,
                    [
                        address["street_address"],
                        address["barangay"],
                        address["city_municipality"],
                        address["province"],
                        address["postal_code"],
                    ]
                )
            )

            order_number = (
                f"IP-{datetime.now():%Y%m%d}-"
                f"{token_hex(5).upper()}"
            )

            # Create pending order.
            cur.execute(
                """
                INSERT INTO orders
                (
                    order_number,
                    checkout_token,
                    user_id,
                    address_id,
                    service_area_id,
                    order_type,
                    status,
                    payment_method,
                    recipient_name,
                    contact_number,
                    delivery_address_snapshot,
                    subtotal,
                    delivery_fee,
                    total_amount,
                    customer_note
                )
                VALUES
                (
                    %s, %s, %s, %s, %s,
                    'delivery',
                    'pending_verification',
                    'cod',
                    %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    order_number,
                    checkout_token,
                    user_id,
                    address["id"],
                    area["id"],
                    address["recipient_name"],
                    address["mobile_number"],
                    snapshot,
                    final_subtotal,
                    delivery_fee,
                    total,
                    note or None,
                ),
            )

            order_id = cur.lastrowid

            for (
                product,
                qty,
                price,
                line_total
            ) in confirmed_items:

                cur.execute(
                    """
                    INSERT INTO order_items
                    (
                        order_id,
                        product_id,
                        product_name_snapshot,
                        unit_price,
                        quantity,
                        line_total
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        product["id"],
                        product["name"],
                        price,
                        qty,
                        line_total,
                    ),
                )

            # Record unpaid COD payment.
            cur.execute(
                """
                INSERT INTO payments
                (
                    order_id,
                    payment_method,
                    amount,
                    status
                )
                VALUES (%s, 'cod', %s, 'unpaid')
                """,
                (order_id, total),
            )

            conn.commit()

        except IntegrityError:

            conn.rollback()

            matched = fetch_all(
                """
                SELECT id
                FROM orders
                WHERE user_id = %s
                  AND checkout_token = %s
                """,
                (user_id, checkout_token),
            )

            if matched:

                return redirect(
                    url_for(
                        "orders.order_detail",
                        order_id=matched[0]["id"]
                    )
                )

            flash(
                "This order could not be placed. "
                "Please try again.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        except ValueError as exc:

            conn.rollback()

            flash(str(exc), "danger")

            return redirect(
                url_for("cart.checkout")
            )

        except Exception:
            conn.rollback()
            raise

        finally:
            cur.close()

        # Clear cart after successful order.
        session.pop("shop_cart", None)
        session.pop("checkout_token", None)

        flash(
            "Order submitted for verification.",
            "success"
        )

        return redirect(
            url_for(
                "orders.order_detail",
                order_id=order_id
            )
        )

    # DISPLAY CHECKOUT

    if "checkout_token" not in session:

        session["checkout_token"] = (
            token_urlsafe(24)
        )

    return render_template(
        "checkout.html",
        items=items,
        subtotal=subtotal,
        addresses=addresses,
        eligible=eligible,
        checkout_token=session["checkout_token"],
        title="Checkout",
    )
