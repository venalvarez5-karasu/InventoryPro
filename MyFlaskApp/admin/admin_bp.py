import re
import unicodedata
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from uuid import uuid4
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
from PIL import Image, ImageOps

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import (
    current_user,
    role_required,
)


admin_bp = Blueprint(
    "admin",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/admin/static",
)

# CONFIGURATION

MAX_IMAGE_BYTES = 5 * 1024 * 1024

IMAGE_FOLDER = (
    Path(__file__).resolve().parent.parent
    / "products"
    / "static"
    / "images"
)

# DATABASE HELPERS

def db_one(query, params=()):
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute(query, params)
        return cursor.fetchone()

    finally:
        cursor.close()


def db_all(query, params=()):
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute(query, params)
        return cursor.fetchall()

    finally:
        cursor.close()


def db_write(query, params=()):
    cursor = mysql.connection.cursor()

    try:
        cursor.execute(query, params)
        inserted_id = cursor.lastrowid

        mysql.connection.commit()

        return inserted_id

    except Exception:
        mysql.connection.rollback()
        raise

    finally:
        cursor.close()

# DASHBOARD DATA

def product_statistics():
    return db_one(
        """
        SELECT
            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN is_active = 1
                    THEN 1 ELSE 0
                END
            ) AS active,

            SUM(
                CASE
                    WHEN is_active = 1
                     AND is_available = 1
                    THEN 1 ELSE 0
                END
            ) AS available,

            SUM(
                CASE
                    WHEN is_active = 0
                    THEN 1 ELSE 0
                END
            ) AS archived

        FROM products
        """
    )


def active_categories():
    return db_all(
        """
        SELECT id, name, slug
        FROM product_categories
        WHERE is_active = 1
        ORDER BY display_order ASC, name ASC
        """
    )


def get_product(product_id):
    return db_one(
        """
        SELECT
            p.*,
            c.name AS category_name
        FROM products p
        INNER JOIN product_categories c
            ON p.category_id = c.id
        WHERE p.id = %s
        """,
        (product_id,),
    )

# PRODUCT SLUG

def slugify(value):
    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = value.encode(
        "ascii",
        "ignore"
    ).decode("ascii")

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")[:170].strip("-")


def unique_product_slug(name):
    base = slugify(name)

    if not base:
        base = "product"

    slug = base
    number = 2

    while db_one(
        """
        SELECT id
        FROM products
        WHERE slug = %s
        LIMIT 1
        """,
        (slug,),
    ):
        slug = f"{base}-{number}"
        number += 1

    return slug

# PRODUCT FORM VALIDATION

def validate_product_form():

    name = request.form.get(
        "name", ""
    ).strip()

    category_raw = request.form.get(
        "category_id", ""
    ).strip()

    description = request.form.get(
        "description", ""
    ).strip()

    price_raw = request.form.get(
        "price", ""
    ).strip()

    is_available = (
        1 if request.form.get("is_available") == "1"
        else 0
    )

    is_made_to_order = (
        1 if request.form.get("is_made_to_order") == "1"
        else 0
    )

    if not 2 <= len(name) <= 180:
        return None, (
            "Product name must contain "
            "2 to 180 characters."
        )

    if len(description) > 2000:
        return None, (
            "Description must not exceed "
            "2,000 characters."
        )

    if not category_raw.isdigit():
        return None, "Select a valid category."

    category_id = int(category_raw)

    category = db_one(
        """
        SELECT id
        FROM product_categories
        WHERE id = %s
          AND is_active = 1
        """,
        (category_id,),
    )

    if not category:
        return None, (
            "The selected category "
            "is not available."
        )

    try:
        price = Decimal(price_raw)

        if (
            not price.is_finite()
            or price <= 0
            or price > Decimal("99999999.99")
        ):
            return None, (
                "Enter a valid price greater than zero."
            )

        price = price.quantize(
            Decimal("0.01")
        )

    except (InvalidOperation, ValueError):
        return None, (
            "Enter a valid numeric price."
        )

    return {
        "name": name,
        "category_id": category_id,
        "description": description,
        "price": price,
        "is_available": is_available,
        "is_made_to_order": is_made_to_order,
    }, None

# IMAGE UPLOAD HELPER

def save_product_image(upload):

    if not upload or not upload.filename:
        return None

    raw = upload.stream.read(
        MAX_IMAGE_BYTES + 1
    )

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(
            "Image must not exceed 5 MB."
        )

    if not raw:
        raise ValueError(
            "The selected image is empty."
        )

    try:
        with Image.open(BytesIO(raw)) as original:

            if original.format not in (
                "JPEG",
                "PNG",
                "WEBP",
            ):
                raise ValueError(
                    "Only JPG, PNG, and WEBP "
                    "images are allowed."
                )

            if (
                original.width * original.height
                > 16000000
            ):
                raise ValueError(
                    "Image dimensions are too large."
                )

            image = ImageOps.exif_transpose(
                original
            )

            image.thumbnail(
                (1200, 1200),
                Image.Resampling.LANCZOS
            )

            rgba = image.convert("RGBA")

            background = Image.new(
                "RGB",
                rgba.size,
                (255, 255, 255)
            )

            background.paste(
                rgba,
                mask=rgba.getchannel("A")
            )

            filename = f"{uuid4().hex}.webp"

            IMAGE_FOLDER.mkdir(
                parents=True,
                exist_ok=True
            )

            background.save(
                IMAGE_FOLDER / filename,
                "WEBP",
                quality=85,
                method=4
            )

            return filename

    except ValueError:
        raise

    except Exception as error:
        raise ValueError(
            "The uploaded file is not a valid image."
        ) from error


def remove_product_image(filename):

    if not filename:
        return

    # Only remove images from our upload directory.
    # Never accept arbitrary filesystem paths.
    if Path(filename).name != filename:
        return

    file_path = IMAGE_FOLDER / filename

    try:
        if file_path.is_file():
            file_path.unlink()

    except OSError:
        current_app.logger.exception(
            "Unable to remove product image"
        )

# ADMIN DASHBOARD

@admin_bp.route("/")
@role_required("admin")
def dashboard():

    from .admin import dashboard_extra

    stats = product_statistics()

    recent_products = db_all(
        """
        SELECT
            p.id,
            p.name,
            p.price,
            p.image_path,
            p.is_active,
            p.is_available,
            c.name AS category_name
        FROM products p
        INNER JOIN product_categories c
            ON p.category_id = c.id
        ORDER BY p.updated_at DESC, p.id DESC
        LIMIT 6
        """
    )

    (
        overview,
        customer_count,
        low_stock,
        recent_orders
    ) = dashboard_extra()

    low_stock_count = db_one(
        """
        SELECT COUNT(*) AS n
        FROM inventory_items
        WHERE is_active = 1
          AND reorder_level > 0
          AND quantity_on_hand <= reorder_level
        """
    )["n"]

    return render_template(
        "admin_dashboard.html",
        title="Dashboard",
        user=current_user(),
        stats=stats,
        recent_products=recent_products,
        overview=overview,
        customer_count=customer_count,
        low_stock=low_stock,
        low_stock_count=low_stock_count,
        recent_orders=recent_orders,
    )

# MANAGE PRODUCTS

@admin_bp.route("/products")
@role_required("admin")
def manage_products():

    search = request.args.get(
        "q", ""
    ).strip()[:80]

    status = request.args.get(
        "status", "active"
    ).strip()

    if status not in ("active", "archived"):
        status = "active"

    is_active = 1 if status == "active" else 0

    page = request.args.get(
        "page", default=1, type=int
    )

    page = max(1, min(page or 1, 100000))

    per_page = 10

    where_clause = "p.is_active = %s"
    params = [is_active]

    if search:
        where_clause += """
            AND (
                p.name LIKE %s
                OR c.name LIKE %s
            )
        """

        keyword = f"%{search}%"

        params.extend([keyword, keyword])

    total = db_one(
        f"""
        SELECT COUNT(*) AS total
        FROM products p
        INNER JOIN product_categories c
            ON p.category_id = c.id
        WHERE {where_clause}
        """,
        tuple(params)
    )["total"]

    pages = max(
        1,
        (total + per_page - 1) // per_page
    )

    page = min(page, pages)
    offset = (page - 1) * per_page

    products = db_all(
        f"""
        SELECT
            p.id,
            p.name,
            p.slug,
            p.description,
            p.price,
            p.image_path,
            p.is_active,
            p.is_available,
            p.is_made_to_order,
            c.name AS category_name
        FROM products p
        INNER JOIN product_categories c
            ON p.category_id = c.id
        WHERE {where_clause}
        ORDER BY p.updated_at DESC, p.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [per_page, offset]),
    )

    return render_template(
        "manage_products.html",
        title="Manage Products",
        user=current_user(),
        stats=product_statistics(),
        products=products,
        search=search,
        status=status,
        page=page,
        pages=pages,
        total=total,
    )

# ADD PRODUCT

@admin_bp.route(
    "/products/add",
    methods=["GET", "POST"]
)
@role_required("admin")
def add_product():

    categories = active_categories()

    if request.method == "POST":

        data, error = validate_product_form()

        if error:
            flash(error, "danger")

            return render_template(
                "product_form.html",
                title="Add Product",
                user=current_user(),
                categories=categories,
                product=None,
                form_action=url_for(
                    "admin.add_product"
                ),
            ), 400

        new_image = None

        try:
            new_image = save_product_image(
                request.files.get("image")
            )

            product_slug = unique_product_slug(
                data["name"]
            )

            db_write(
                """
                INSERT INTO products
                (
                    category_id,
                    name,
                    slug,
                    description,
                    price,
                    image_path,
                    is_active,
                    is_available,
                    is_made_to_order
                )
                VALUES
                (
                    %s, %s, %s, %s,
                    %s, %s, 1, %s, %s
                )
                """,
                (
                    data["category_id"],
                    data["name"],
                    product_slug,
                    data["description"],
                    data["price"],
                    new_image,
                    data["is_available"],
                    data["is_made_to_order"],
                ),
            )

            flash(
                "Product added successfully.",
                "success"
            )

            return redirect(
                url_for("admin.manage_products")
            )

        except ValueError as error:
            if new_image:
                remove_product_image(new_image)

            flash(str(error), "danger")

        except Exception:
            if new_image:
                remove_product_image(new_image)

            current_app.logger.exception(
                "Unable to add product"
            )

            flash(
                "Could not add the product. "
                "Please check the details.",
                "danger"
            )

        return render_template(
            "product_form.html",
            title="Add Product",
            user=current_user(),
            categories=categories,
            product=None,
            form_action=url_for(
                "admin.add_product"
            ),
        ), 400

    return render_template(
        "product_form.html",
        title="Add Product",
        user=current_user(),
        categories=categories,
        product=None,
        form_action=url_for(
            "admin.add_product"
        ),
    )

# EDIT PRODUCT

@admin_bp.route(
    "/products/<int:product_id>/edit",
    methods=["GET", "POST"]
)
@role_required("admin")
def edit_product(product_id):

    product = get_product(product_id)

    if not product:
        abort(404)

    if not product["is_active"]:
        flash(
            "Restore this product before editing.",
            "warning"
        )

        return redirect(
            url_for(
                "admin.manage_products",
                status="archived"
            )
        )

    categories = active_categories()

    if request.method == "POST":

        data, error = validate_product_form()

        if error:
            flash(error, "danger")

            return render_template(
                "product_form.html",
                title="Edit Product",
                user=current_user(),
                categories=categories,
                product=product,
                form_action=url_for(
                    "admin.edit_product",
                    product_id=product_id
                ),
            ), 400

        new_image = None

        try:
            new_image = save_product_image(
                request.files.get("image")
            )

            image_path = (
                new_image
                if new_image
                else product["image_path"]
            )

            db_write(
                """
                UPDATE products
                SET
                    category_id = %s,
                    name = %s,
                    description = %s,
                    price = %s,
                    image_path = %s,
                    is_available = %s,
                    is_made_to_order = %s
                WHERE id = %s
                  AND is_active = 1
                """,
                (
                    data["category_id"],
                    data["name"],
                    data["description"],
                    data["price"],
                    image_path,
                    data["is_available"],
                    data["is_made_to_order"],
                    product_id,
                ),
            )

            if new_image and product["image_path"]:
                remove_product_image(
                    product["image_path"]
                )

            flash(
                "Product updated successfully.",
                "success"
            )

            return redirect(
                url_for("admin.manage_products")
            )

        except ValueError as error:
            if new_image:
                remove_product_image(new_image)

            flash(str(error), "danger")

        except Exception:
            if new_image:
                remove_product_image(new_image)

            current_app.logger.exception(
                "Unable to update product"
            )

            flash(
                "Could not update the product.",
                "danger"
            )

        return render_template(
            "product_form.html",
            title="Edit Product",
            user=current_user(),
            categories=categories,
            product=product,
            form_action=url_for(
                "admin.edit_product",
                product_id=product_id
            ),
        ), 400

    return render_template(
        "product_form.html",
        title="Edit Product",
        user=current_user(),
        categories=categories,
        product=product,
        form_action=url_for(
            "admin.edit_product",
            product_id=product_id
        ),
    )

# TOGGLE PRODUCT AVAILABILITY

@admin_bp.route(
    "/products/<int:product_id>/availability",
    methods=["POST"]
)
@role_required("admin")
def toggle_availability(product_id):

    product = get_product(product_id)

    if not product:
        abort(404)

    if not product["is_active"]:
        flash(
            "Archived products cannot be enabled.",
            "warning"
        )

    else:
        db_write(
            """
            UPDATE products
            SET is_available =
                CASE
                    WHEN is_available = 1
                    THEN 0 ELSE 1
                END
            WHERE id = %s
              AND is_active = 1
            """,
            (product_id,),
        )

        flash(
            "Product availability updated.",
            "success"
        )

    return redirect(
        url_for("admin.manage_products")
    )

# ARCHIVE PRODUCT

@admin_bp.route(
    "/products/<int:product_id>/archive",
    methods=["POST"]
)
@role_required("admin")
def archive_product(product_id):

    product = get_product(product_id)

    if not product:
        abort(404)

    db_write(
        """
        UPDATE products
        SET
            is_active = 0,
            is_available = 0
        WHERE id = %s
        """,
        (product_id,),
    )

    flash(
        "Product archived successfully.",
        "success"
    )

    return redirect(
        url_for("admin.manage_products")
    )

# RESTORE ARCHIVED PRODUCT

@admin_bp.route(
    "/products/<int:product_id>/restore",
    methods=["POST"]
)
@role_required("admin")
def restore_product(product_id):

    product = get_product(product_id)

    if not product:
        abort(404)

    # Product remains unavailable until
    # an admin explicitly enables ordering.
    db_write(
        """
        UPDATE products
        SET
            is_active = 1,
            is_available = 0
        WHERE id = %s
        """,
        (product_id,),
    )

    flash(
        "Product restored. "
        "Ordering is still disabled.",
        "success"
    )

    return redirect(
        url_for("admin.manage_products")
    )
    
from . import admin
from . import notification
