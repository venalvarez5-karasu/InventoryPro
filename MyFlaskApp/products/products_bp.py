from flask import (
    Blueprint,
    abort,
    render_template,
    request,
)
from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql


products_bp = Blueprint(
    "products",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/products/static",
)

PRODUCTS_PER_PAGE = 9


def fetch_categories():
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute(
            """
            SELECT id, name, slug
            FROM product_categories
            WHERE is_active = 1
            ORDER BY display_order ASC, name ASC
            """
        )

        return cursor.fetchall()

    finally:
        cursor.close()


@products_bp.route("/")
def browse():
    search = request.args.get(
        "q", "", type=str
    ).strip()[:80]

    category = request.args.get(
        "category", "", type=str
    ).strip()[:110]

    page = request.args.get(
        "page", 1, type=int
    ) or 1

    page = max(1, page)

    categories = fetch_categories()

    # Build parameterized search conditions
    conditions = [
        "p.is_active = 1",
        "c.is_active = 1",
    ]

    params = []

    if search:
        conditions.append(
            "(p.name LIKE %s OR p.description LIKE %s)"
        )

        keyword = f"%{search}%"
        params.extend([keyword, keyword])

    if category:
        conditions.append("c.slug = %s")
        params.append(category)

    where_clause = " AND ".join(conditions)

    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Count matching products
        count_query = f"""
            SELECT COUNT(*) AS total
            FROM products p
            INNER JOIN product_categories c
                ON p.category_id = c.id
            WHERE {where_clause}
        """

        cursor.execute(
            count_query,
            tuple(params)
        )

        total = cursor.fetchone()["total"]

        total_pages = max(
            1,
            (total + PRODUCTS_PER_PAGE - 1)
            // PRODUCTS_PER_PAGE
        )

        page = min(page, total_pages)
        offset = (page - 1) * PRODUCTS_PER_PAGE

        # Read actual menu data
        product_query = f"""
            SELECT
                p.id,
                p.name,
                p.slug,
                p.description,
                p.price,
                p.image_path,
                p.is_available,
                p.is_made_to_order,
                c.name AS category_name,
                c.slug AS category_slug
            FROM products p
            INNER JOIN product_categories c
                ON p.category_id = c.id
            WHERE {where_clause}
            ORDER BY
                c.display_order ASC,
                p.id ASC
            LIMIT %s OFFSET %s
        """

        cursor.execute(
            product_query,
            tuple(params) + (
                PRODUCTS_PER_PAGE,
                offset,
            )
        )

        products = cursor.fetchall()

    finally:
        cursor.close()

    return render_template(
        "browse.html",
        title="Browse Products",
        products=products,
        categories=categories,
        search=search,
        selected_category=category,
        page=page,
        total_pages=total_pages,
        total=total,
    )

# PRODUCT DETAILS

# ==========================================
# PRODUCT DETAILS
# ==========================================

@products_bp.route("/<string:slug>")
def product_detail(slug):

    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Get selected product.
        cursor.execute(
            """
            SELECT
                p.id,
                p.category_id,
                p.name,
                p.slug,
                p.description,
                p.price,
                p.image_path,
                p.is_active,
                p.is_available,
                p.is_made_to_order,
                c.name AS category_name,
                c.slug AS category_slug

            FROM products p

            INNER JOIN product_categories c
                ON p.category_id = c.id

            WHERE p.slug = %s
              AND p.is_active = 1
              AND c.is_active = 1

            LIMIT 1
            """,
            (slug,)
        )

        product = cursor.fetchone()

        if not product:
            abort(404)

        # Recommend up to four other products.
        # Prioritize products in the same category.
        # Fill remaining slots from other categories.
        cursor.execute(
            """
            SELECT
                p.id,
                p.name,
                p.slug,
                p.price,
                p.image_path,
                p.is_available,
                c.name AS category_name,
                c.slug AS category_slug

            FROM products p

            INNER JOIN product_categories c
                ON p.category_id = c.id

            WHERE p.id <> %s
              AND p.is_active = 1
              AND c.is_active = 1

            ORDER BY
                CASE
                    WHEN p.category_id = %s THEN 0
                    ELSE 1
                END ASC,
                p.is_available DESC,
                p.id ASC

            LIMIT 4
            """,
            (
                product["id"],
                product["category_id"]
            )
        )

        related_products = cursor.fetchall()

    finally:
        cursor.close()

    return render_template(
        "product_detail.html",
        title=product["name"],
        product=product,
        related_products=related_products
    )
