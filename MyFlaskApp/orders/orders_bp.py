from flask import (
    Blueprint,
    redirect,
    render_template,
    url_for,
    abort,
    flash,
)

from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import current_user


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


@orders_bp.route("/<int:order_id>")
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

    return render_template(
        "order_detail.html",
        order=orders[0],
        items=items,
        title="Order Details",
    )
