
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from secrets import token_hex, token_urlsafe
from zoneinfo import ZoneInfo
import re

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    abort,
    jsonify,
    current_app,
)

from MySQLdb.cursors import DictCursor
from MySQLdb import IntegrityError

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user


cart_bp = Blueprint(
    "cart",
    __name__,
    template_folder="templates",
    static_folder="static",
)

MAX_DISTINCT = 25
MAX_QUANTITY = 99

MANILA = ZoneInfo("Asia/Manila")


# DATABASE HELPERS

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


# CUSTOMER HEADER MINI CART

@cart_bp.app_context_processor
def inject_store_header_cart():

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


# ELIGIBLE DELIVERY ADDRESSES

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
                    == normalize(address["city_municipality"])
                    and same_province(
                        address["province"],
                        area["region_name"]
                    )
                )
            ),
            None,
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
    from urllib.parse import urlsplit

    def return_to_browsing():
        # Only redirect to pages on this website.
        previous = request.referrer
        fallback = url_for("products.browse")

        if not previous:
            return redirect(fallback)

        target = urlsplit(previous)
        current = urlsplit(request.host_url)

        if (
            target.scheme not in ("http", "https")
            or target.netloc != current.netloc
            or target.path.startswith("/cart/")
        ):
            return redirect(fallback)

        return redirect(previous)

    product_id = request.form.get(
        "product_id", type=int
    )

    qty = request.form.get(
        "quantity", default=1, type=int
    )

    if not product_id or not 1 <= qty <= MAX_QUANTITY:
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
        return return_to_browsing()

    cart = dict(session.get("shop_cart", {}))

    if (
        str(product_id) not in cart
        and len(cart) >= MAX_DISTINCT
    ):
        flash(
            "Cart can contain up to 25 different products.",
            "warning"
        )
        return return_to_browsing()

    cart[str(product_id)] = min(
        MAX_QUANTITY,
        int(cart.get(str(product_id), 0)) + qty
    )

    session["shop_cart"] = cart
    session.modified = True

    flash("Product added to your cart.", "success")

    return return_to_browsing()



# UPDATE CART

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
                "error": "Invalid product or quantity.",
            }), 400

        abort(400)

    cart = dict(session.get("shop_cart", {}))

    if qty == 0:
        cart.pop(str(product_id), None)

    elif str(product_id) in cart:
        cart[str(product_id)] = qty

    session["shop_cart"] = cart
    session.modified = True

    if is_ajax:

        items, subtotal = get_lines()

        updated_item = next(
            (
                item
                for item in items
                if int(item["id"]) == product_id
            ),
            None,
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
            ),
        })

    return redirect(
        url_for("cart.view_cart")
    )


# CHECKOUT

@cart_bp.route("/checkout", methods=["GET", "POST"])
def checkout():

    user = current_user()

    if not user:
        return redirect(
            url_for(
                "auth.login",
                next=url_for("cart.checkout")
            )
        )

    items, subtotal = get_lines()

    if not items:

        flash("Your cart is empty.", "warning")

        return redirect(
            url_for("cart.view_cart")
        )

    addresses, eligible = approved_addresses(user["id"])

    settings = fetch_all(
        """
        SELECT pickup_enabled, deposit_percent
        FROM store_pickup_settings
        WHERE id = 1
        """
    )

    pickup_enabled = bool(
        settings and settings[0]["pickup_enabled"]
    )

    percent = (
        Decimal(str(settings[0]["deposit_percent"]))
        if settings
        else Decimal("20")
    )

    slots = current_app.config.get(
        "PICKUP_TIME_SLOTS",
        [
            "09:00",
            "10:00",
            "11:00",
            "13:00",
            "14:00",
            "15:00",
            "16:00",
        ],
    )

    if isinstance(slots, str):
        slots = [
            slot.strip()
            for slot in slots.split(",")
            if slot.strip()
        ]

    slots = list(slots)

    today = datetime.now(MANILA).date()

    areas = fetch_all(
        """
        SELECT
            s.city_municipality,
            r.name AS province,
            s.delivery_fee
        FROM service_areas s
        JOIN service_regions r
            ON r.id = s.region_id
        WHERE s.is_enabled = 1
          AND s.cod_enabled = 1
          AND r.is_active = 1
          AND s.delivery_fee IS NOT NULL
        ORDER BY r.name, s.city_municipality
        """
    )

    if request.method == "POST":

        method = request.form.get(
            "order_type", ""
        )

        payment = request.form.get(
            "payment_method", ""
        )

        if (
            method not in ("delivery", "pickup")
            or (
                method == "pickup"
                and not pickup_enabled
            )
        ):

            flash(
                "Invalid or disabled fulfillment method.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        if (
            (
                method == "delivery"
                and payment not in ("cod", "gcash")
            )
            or (
                method == "pickup"
                and payment != "gcash"
            )
        ):

            flash("Invalid payment method.", "danger")

            return redirect(
                url_for("cart.checkout")
            )

        token = request.form.get(
            "checkout_token", ""
        )

        if (
            not token
            or token != session.get("checkout_token")
        ):

            existing = (
                fetch_all(
                    """
                    SELECT id
                    FROM orders
                    WHERE user_id = %s
                      AND checkout_token = %s
                    """,
                    (user["id"], token),
                )
                if token
                else []
            )

            if existing:
                return redirect(
                    url_for(
                        "orders.order_detail",
                        order_id=existing[0]["id"]
                    )
                )

            flash(
                "Checkout expired. Please review again.",
                "warning"
            )

            return redirect(
                url_for("cart.checkout")
            )

        note = request.form.get(
            "customer_note", ""
        ).strip()

        if len(note) > 500:

            flash(
                "Order notes cannot exceed 500 characters.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        address_id = (
            request.form.get("address_id", type=int)
            if method == "delivery"
            else None
        )

        if method == "delivery":

            if not any(
                address["id"] == address_id
                for address in eligible
            ):

                flash(
                    "Select an approved delivery address.",
                    "danger"
                )

                return redirect(
                    url_for("cart.checkout")
                )

        requested_date = None
        requested_time = None

        if method == "pickup":

            try:
                requested_date = date.fromisoformat(
                    request.form.get("requested_date", "")
                )

            except (ValueError, TypeError):
                requested_date = None

            requested_time = request.form.get(
                "requested_time", ""
            )

            if (
                not requested_date
                or not (
                    today
                    <= requested_date
                    <= today + timedelta(days=30)
                )
                or requested_time not in slots
            ):

                flash(
                    "Choose a valid pickup date and time.",
                    "danger"
                )

                return redirect(
                    url_for("cart.checkout")
                )

            if requested_date == today:

                try:
                    hour, minute = (
                        int(value)
                        for value in requested_time.split(":")
                    )

                    now = datetime.now(MANILA)

                    if (hour, minute) <= (
                        now.hour,
                        now.minute
                    ):
                        raise ValueError

                except (ValueError, TypeError):

                    flash(
                        "Select a future pickup time.",
                        "danger"
                    )

                    return redirect(
                        url_for("cart.checkout")
                    )

        conn = mysql.connection
        cur = conn.cursor(DictCursor)

        try:
            conn.begin()

            address = None
            area = None

            delivery_fee = Decimal("0.00")
            snapshot = None

            recipient = (
                str(user.get("first_name") or "")
                + " "
                + str(user.get("last_name") or "")
            ).strip()

            contact = user.get("mobile_number") or ""

            if method == "delivery":

                cur.execute(
                    """
                    SELECT *
                    FROM customer_addresses
                    WHERE id = %s
                      AND user_id = %s
                    FOR UPDATE
                    """,
                    (address_id, user["id"]),
                )

                address = cur.fetchone()

                if not address:
                    raise ValueError(
                        "Selected address is no longer available."
                    )

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
                      AND r.is_active = 1
                      AND s.delivery_fee IS NOT NULL
                    FOR UPDATE
                    """
                )

                area = next(
                    (
                        row
                        for row in cur.fetchall()
                        if (
                            normalize(
                                row["city_municipality"]
                            ) == normalize(
                                address["city_municipality"]
                            )
                            and same_province(
                                address["province"],
                                row["region_name"]
                            )
                        )
                    ),
                    None,
                )

                if not area:
                    raise ValueError(
                        "Delivery is unavailable at this address."
                    )

                delivery_fee = Decimal(
                    str(area["delivery_fee"])
                )

                recipient = address["recipient_name"]
                contact = address["mobile_number"]

                snapshot = ", ".join(
                    str(value)
                    for value in [
                        address["street_address"],
                        address["barangay"],
                        address["city_municipality"],
                        address["province"],
                        address["postal_code"],
                    ]
                    if value
                )

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
                        f"{line['name']} is no longer available."
                    )

                quantity = int(line["quantity"])
                price = Decimal(str(product["price"]))
                line_total = price * quantity

                confirmed_items.append(
                    (
                        product,
                        quantity,
                        price,
                        line_total
                    )
                )

                final_subtotal += line_total

            total = final_subtotal + delivery_fee

            if method == "pickup":

                deposit = (
                    total
                    * percent
                    / Decimal("100")
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP
                )

                balance = total - deposit

            else:

                deposit = Decimal("0.00")
                balance = Decimal("0.00")

            order_number = (
                f"IP-{datetime.now(MANILA):%Y%m%d}-"
                f"{token_hex(5).upper()}"
            )

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
                    customer_note,
                    requested_date,
                    requested_time,
                    pickup_deposit_due,
                    pickup_balance_due
                )
                VALUES
                (
                    %s, %s, %s, %s, %s, %s,
                    'pending_verification',
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    order_number,
                    token,
                    user["id"],
                    address["id"] if address else None,
                    area["id"] if area else None,
                    method,
                    payment,
                    recipient,
                    contact,
                    snapshot,
                    final_subtotal,
                    delivery_fee,
                    total,
                    note or None,
                    requested_date,
                    requested_time or None,
                    deposit,
                    balance,
                ),
            )

            order_id = cur.lastrowid

            for (
                product,
                quantity,
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
                        quantity,
                        line_total,
                    ),
                )

            # Pickup deposit is submitted later
            # using the existing order-details form.

            if method == "delivery":

                cur.execute(
                    """
                    INSERT INTO payments
                    (
                        order_id,
                        payment_method,
                        amount,
                        status
                    )
                    VALUES (%s, %s, %s, 'unpaid')
                    """,
                    (
                        order_id,
                        payment,
                        total
                    ),
                )

            conn.commit()

        except ValueError as exc:

            conn.rollback()

            flash(str(exc), "danger")

            return redirect(
                url_for("cart.checkout")
            )

        except IntegrityError:

            conn.rollback()

            duplicate = fetch_all(
                """
                SELECT id
                FROM orders
                WHERE user_id = %s
                  AND checkout_token = %s
                """,
                (user["id"], token),
            )

            if duplicate:
                return redirect(
                    url_for(
                        "orders.order_detail",
                        order_id=duplicate[0]["id"]
                    )
                )

            flash(
                "Order was not saved. Please try again.",
                "danger"
            )

            return redirect(
                url_for("cart.checkout")
            )

        except Exception:

            conn.rollback()
            raise

        finally:

            cur.close()

        session.pop("shop_cart", None)
        session.pop("checkout_token", None)

        if payment == "gcash":

            flash(
                "Order placed. Submit your GCash "
                "reference on the order details page.",
                "success"
            )

        else:

            flash(
                "COD order submitted for verification.",
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
        session["checkout_token"] = token_urlsafe(24)

    return render_template(
        "checkout.html",
        items=items,
        subtotal=subtotal,
        eligible=eligible,
        addresses=addresses,
        checkout_token=session["checkout_token"],
        pickup_enabled=pickup_enabled,
        deposit_percent=percent,
        pickup_slots=slots,
        today=today.isoformat(),
        max_date=(
            today + timedelta(days=30)
        ).isoformat(),
        service_areas=areas,
        title="Checkout",
    )


# ADD ADDRESS WITHOUT LEAVING CHECKOUT

@cart_bp.post("/address")
def add_checkout_address():

    from MyFlaskApp.auth.auth_bp import (
        valid_selected_address,
        valid_name,
        valid_address_text,
    )

    user = current_user()

    if not user:
        return jsonify({
            "error": "Please sign in."
        }), 401

    payload = request.get_json(silent=True) or {}

    name = str(
        payload.get("recipient_name", "")
    ).strip()

    phone = str(
        payload.get("mobile_number", "")
    ).strip()

    province = str(
        payload.get("province", "")
    ).strip()

    city = str(
        payload.get("city_municipality", "")
    ).strip()

    barangay = str(
        payload.get("barangay", "")
    ).strip()

    street = str(
        payload.get("street_address", "")
    ).strip()

    postal = str(
        payload.get("postal_code", "")
    ).strip()

    if (
        not valid_name(name, 160)
        or not re.fullmatch(r"09\d{9}", phone)
        or not valid_address_text(street, 255, 3)
        or not re.fullmatch(r"\d{4}", postal)
    ):

        return jsonify({
            "error": (
                "Check recipient name, phone, "
                "street, and postal code."
            )
        }), 400

    if not (
        valid_address_text(province, 100)
        and valid_address_text(city, 100)
        and valid_address_text(barangay, 120, 1)
    ):

        return jsonify({
            "error": "Invalid address fields."
        }), 400

    areas = fetch_all(
        """
        SELECT
            s.delivery_fee,
            s.city_municipality,
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

    matched = next(
        (
            area
            for area in areas
            if (
                normalize(area["city_municipality"])
                == normalize(city)
                and same_province(
                    province,
                    area["region_name"]
                )
            )
        ),
        None,
    )

    if not matched:

        return jsonify({
            "error": (
                "This city is not covered by "
                "the bakery's delivery areas."
            )
        }), 400

    if not valid_selected_address(
        province,
        city,
        barangay
    ):

        return jsonify({
            "error": (
                "Select a valid city and barangay "
                "from the dropdowns."
            )
        }), 400

    conn = mysql.connection
    cur = conn.cursor(DictCursor)

    try:

        cur.execute(
            """
            SELECT COUNT(*) AS total
            FROM customer_addresses
            WHERE user_id = %s
            """,
            (user["id"],),
        )

        first_address = (
            int(cur.fetchone()["total"]) == 0
        )

        cur.execute(
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
            (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user["id"],
                name,
                phone,
                province,
                city,
                barangay,
                street,
                postal,
                1 if first_address else 0,
            ),
        )

        address_id = cur.lastrowid
        conn.commit()

    except Exception:

        conn.rollback()
        raise

    finally:

        cur.close()

    return jsonify({
        "id": address_id,
        "recipient": f"{name} | {phone}",
        "address": (
            f"{street}, {barangay}, {city}, "
            f"{province}, {postal}"
        ),
        "fee": str(matched["delivery_fee"]),
    }), 201


# SUBMIT DELIVERY GCASH REFERENCE

@cart_bp.post(
    "/orders/<int:order_id>/gcash-reference"
)
def submit_delivery_gcash_reference(order_id):

    user = current_user()

    if not user:
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
            "Enter a valid GCash reference number.",
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
                payment_method,
                status,
                total_amount
            FROM orders
            WHERE id = %s
              AND user_id = %s
            FOR UPDATE
            """,
            (order_id, user["id"]),
        )

        order = cur.fetchone()

        if not order:
            abort(404)

        if (
            order["order_type"] != "delivery"
            or order["payment_method"] != "gcash"
            or order["status"] not in (
                "pending_verification",
                "pending",
            )
        ):

            raise ValueError(
                "This order cannot accept a GCash reference."
            )

        cur.execute(
            """
            SELECT id
            FROM payments
            WHERE order_id = %s
              AND status IN ('pending_review', 'paid')
            """,
            (order_id,),
        )

        if cur.fetchone():

            raise ValueError(
                "Payment is already under review or verified."
            )

        cur.execute(
            """
            SELECT id
            FROM payments
            WHERE payment_method = 'gcash'
              AND payment_reference = %s
            LIMIT 1
            """,
            (reference,),
        )

        if cur.fetchone():

            raise ValueError(
                "This reference has already been submitted."
            )

        cur.execute(
            """
            UPDATE payments
            SET
                payment_reference = %s,
                status = 'pending_review'
            WHERE order_id = %s
              AND payment_method = 'gcash'
              AND status = 'unpaid'
            """,
            (reference, order_id),
        )

        if not cur.rowcount:

            cur.execute(
                """
                INSERT INTO payments
                (
                    order_id,
                    payment_method,
                    amount,
                    status,
                    payment_reference
                )
                VALUES
                (%s, 'gcash', %s, 'pending_review', %s)
                """,
                (
                    order_id,
                    order["total_amount"],
                    reference,
                ),
            )

        conn.commit()

        flash(
            "GCash reference submitted for Admin review.",
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
