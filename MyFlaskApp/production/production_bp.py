
"""Recipe management and per-product estimated costs."""

from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint, flash, redirect,
    render_template, request, url_for, abort
)

from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql

from MyFlaskApp.auth.auth_bp import (
    current_user, role_required
)


production_bp = Blueprint(
    "production",
    __name__,
    template_folder="templates",
)


def rows(sql, args=()):

    cur = mysql.connection.cursor(DictCursor)

    try:
        cur.execute(sql, args)
        return cur.fetchall()

    finally:
        cur.close()


def one(sql, args=()):

    result = rows(sql, args)
    return result[0] if result else None


def positive_decimal(value, precision="0.001"):

    try:
        number = Decimal(str(value))

        if (
            not number.is_finite()
            or number <= 0
            or number > Decimal("999999999.999")
        ):
            raise ValueError()

        if number != number.quantize(
            Decimal(precision)
        ):
            raise ValueError()

        return number

    except (ValueError, InvalidOperation, TypeError):
        raise ValueError(
            "Enter a positive quantity "
            "with up to three decimal places."
        )


# ==========================================
# RECIPE LIST + PRODUCT COSTING
# ==========================================

@production_bp.route("/")
@role_required("admin")
def recipe_list():

    products = rows(
        """
        SELECT
            p.id,
            p.name,
            p.price,
            c.name AS category_name,
            r.id AS recipe_id,
            r.yield_pieces,

            SUM(
                CASE
                    WHEN ri.id IS NOT NULL
                     AND i.unit_cost IS NULL
                    THEN 1 ELSE 0
                END
            ) AS missing_prices,

            COUNT(ri.id) AS ingredient_count,

            COALESCE(
                SUM(
                    ri.quantity_per_batch * i.unit_cost
                ), 0
            ) AS batch_cost

        FROM products p

        JOIN product_categories c
            ON c.id = p.category_id

        LEFT JOIN recipes r
            ON r.product_id = p.id
           AND r.is_active = 1

        LEFT JOIN recipe_ingredients ri
            ON ri.recipe_id = r.id

        LEFT JOIN inventory_items i
            ON i.id = ri.inventory_item_id

        WHERE p.is_active = 1

        GROUP BY
            p.id,
            p.name,
            p.price,
            c.name,
            r.id,
            r.yield_pieces

        ORDER BY c.display_order, p.name
        """
    )

    for product in products:

        complete = (
            product["recipe_id"]
            and product["ingredient_count"]
            and not product["missing_prices"]
        )

        if complete:
            product["cost_each"] = (
                Decimal(str(product["batch_cost"]))
                / product["yield_pieces"]
            )

            price = Decimal(str(product["price"]))

            product["margin"] = (
                (price - product["cost_each"])
                / price * 100
            ) if price > 0 else None

        else:
            product["cost_each"] = None
            product["margin"] = None

    cost_items = rows(
        """
        SELECT
            id,
            item_name,
            unit,
            unit_cost
        FROM inventory_items
        WHERE is_active = 1
          AND item_type IN (
              'ingredient',
              'packaging'
          )
        ORDER BY item_name
        """
    )

    return render_template(
        "recipe_list.html",
        title="Recipes & Costs",
        user=current_user(),
        products=products,
        cost_items=cost_items,
    )


# ==========================================
# CREATE / EDIT RECIPE
# ==========================================

@production_bp.route(
    "/recipes/<int:product_id>",
    methods=["GET", "POST"]
)
@role_required("admin")
def recipe_edit(product_id):

    product = one(
        """
        SELECT id, name, price
        FROM products
        WHERE id = %s
          AND is_active = 1
        """,
        (product_id,),
    )

    if not product:
        abort(404)

    stock = rows(
        """
        SELECT
            id,
            item_name,
            unit,
            unit_cost,
            quantity_on_hand
        FROM inventory_items
        WHERE is_active = 1
          AND item_type IN (
              'ingredient',
              'packaging'
          )
        ORDER BY item_name
        """
    )

    stock_by_id = {
        item["id"]: item
        for item in stock
    }

    recipe = one(
        """
        SELECT *
        FROM recipes
        WHERE product_id = %s
        """,
        (product_id,),
    )

    ingredients = rows(
        """
        SELECT
            inventory_item_id,
            quantity_per_batch
        FROM recipe_ingredients
        WHERE recipe_id = %s
        ORDER BY id
        """,
        (recipe["id"],),
    ) if recipe else []

    if request.method == "POST":

        try:
            yield_raw = request.form.get(
                "yield_pieces", ""
            )

            if (
                not yield_raw.isdigit()
                or not 1 <= int(yield_raw) <= 100000
            ):
                raise ValueError(
                    "Yield must be a whole number "
                    "from 1 to 100,000."
                )

            count = int(yield_raw)

            instruction = request.form.get(
                "instructions", ""
            ).strip()

            if len(instruction) > 4000:
                raise ValueError(
                    "Instructions must be "
                    "4,000 characters or fewer."
                )

            ids = request.form.getlist("item_id")
            quantities = request.form.getlist(
                "quantity"
            )

            if (
                len(ids) != len(quantities)
                or not 1 <= len(ids) <= 50
            ):
                raise ValueError(
                    "Add between 1 and 50 ingredients."
                )

            chosen = {}

            for raw_id, raw_qty in zip(
                ids, quantities
            ):

                if (
                    not raw_id.isdigit()
                    or int(raw_id) not in stock_by_id
                ):
                    raise ValueError(
                        "Invalid ingredient selected."
                    )

                item_id = int(raw_id)

                if item_id in chosen:
                    raise ValueError(
                        "Each ingredient can appear "
                        "only once."
                    )

                chosen[item_id] = positive_decimal(
                    raw_qty
                )

            conn = mysql.connection
            cur = conn.cursor(DictCursor)

            try:
                conn.begin()

                if recipe:

                    cur.execute(
                        """
                        UPDATE recipes
                        SET
                            yield_pieces = %s,
                            instructions = %s,
                            is_active = 1
                        WHERE id = %s
                        """,
                        (
                            count,
                            instruction,
                            recipe["id"],
                        ),
                    )

                    recipe_id = recipe["id"]

                    cur.execute(
                        """
                        DELETE FROM recipe_ingredients
                        WHERE recipe_id = %s
                        """,
                        (recipe_id,),
                    )

                else:

                    cur.execute(
                        """
                        INSERT INTO recipes
                        (
                            product_id,
                            yield_pieces,
                            instructions
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (
                            product_id,
                            count,
                            instruction,
                        ),
                    )

                    recipe_id = cur.lastrowid

                for item_id, qty in chosen.items():

                    cur.execute(
                        """
                        INSERT INTO recipe_ingredients
                        (
                            recipe_id,
                            inventory_item_id,
                            quantity_per_batch
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (
                            recipe_id,
                            item_id,
                            qty,
                        ),
                    )

                conn.commit()

            except Exception:
                conn.rollback()
                raise

            finally:
                cur.close()

            flash(
                "Recipe saved. Set ingredient "
                "unit costs to calculate margin.",
                "success"
            )

            return redirect(
                url_for("production.recipe_list")
            )

        except ValueError as exc:
            flash(str(exc), "danger")

    return render_template(
        "recipe_form.html",
        title="Edit Recipe",
        user=current_user(),
        product=product,
        recipe=recipe,
        ingredients=ingredients,
        stock=stock,
    )


# ==========================================
# UPDATE INGREDIENT COST
# ==========================================

@production_bp.route(
    "/costs/<int:item_id>",
    methods=["POST"]
)
@role_required("admin")
def save_unit_cost(item_id):

    item = one(
        """
        SELECT id
        FROM inventory_items
        WHERE id = %s
          AND is_active = 1
        """,
        (item_id,),
    )

    if not item:
        abort(404)

    raw = request.form.get(
        "unit_cost", ""
    ).strip()

    try:
        if not raw:
            cost = None

        else:
            cost = Decimal(raw)

            if (
                not cost.is_finite()
                or cost < 0
                or cost > Decimal("99999999.9999")
                or cost != cost.quantize(
                    Decimal("0.0001")
                )
            ):
                raise ValueError()

        cur = mysql.connection.cursor()

        try:
            cur.execute(
                """
                UPDATE inventory_items
                SET unit_cost = %s
                WHERE id = %s
                """,
                (cost, item_id),
            )

            mysql.connection.commit()

        except Exception:
            mysql.connection.rollback()
            raise

        finally:
            cur.close()

        flash(
            "Ingredient cost updated.",
            "success"
        )

    except (ValueError, InvalidOperation):
        flash(
            "Invalid unit cost; use up to "
            "four decimal places.",
            "danger"
        )

    return redirect(
        url_for("production.recipe_list")
    )
