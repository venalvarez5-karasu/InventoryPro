
from flask import Blueprint, render_template
from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql


index_bp = Blueprint(
    "index",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/index/static",
)


@index_bp.route("/")
def home():
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Product categories for homepage navigation
        cursor.execute(
            """
            SELECT id, name, slug
            FROM product_categories
            WHERE is_active = 1
            ORDER BY display_order ASC, name ASC
            """
        )

        categories = cursor.fetchall()

        # Show 6 menu items on the homepage
        # Available products are displayed first.
        cursor.execute(
            """
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
            WHERE p.is_active = 1
              AND c.is_active = 1
            ORDER BY
                p.is_available DESC,
                c.display_order ASC,
                p.id ASC
            LIMIT 6
            """
        )

        featured_products = cursor.fetchall()

    finally:
        cursor.close()

    return render_template(
        "index.html",
        title="Home",
        categories=categories,
        featured_products=featured_products,
    )


@index_bp.route("/about")
def about():
    return render_template(
        "about.html",
        title="About Us",
    )


@index_bp.route("/contact")
def contact():
    return render_template(
        "contact.html",
        title="Contact",
    )
