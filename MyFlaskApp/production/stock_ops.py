
"""Atomic recipe stock usage when an order is confirmed."""

from decimal import Decimal, ROUND_UP


def deduct_order_recipe_stock(cur, order_id, actor_id):

    # The caller must already have an active
    # MySQL transaction and a locked order row.

    cur.execute(
        """
        SELECT id
        FROM stock_movements
        WHERE reference_type = 'order_recipe'
          AND reference_id = %s
          AND movement_type = 'production_use'
        LIMIT 1
        """,
        (order_id,),
    )

    if cur.fetchone():
        raise ValueError(
            "Recipe stock was already consumed "
            "for this order."
        )

    cur.execute(
        """
        SELECT
            oi.product_id,
            oi.quantity,
            oi.product_name_snapshot,
            r.id AS recipe_id,
            r.yield_pieces
        FROM order_items oi
        LEFT JOIN recipes r
            ON r.product_id = oi.product_id
           AND r.is_active = 1
        WHERE oi.order_id = %s
        ORDER BY oi.id
        """,
        (order_id,),
    )

    order_items = cur.fetchall()

    if not order_items:
        raise ValueError(
            "This order has no line items."
        )

    required = {}

    for line in order_items:

        if not line["recipe_id"] or not line["yield_pieces"]:
            raise ValueError(
                "Add an active recipe for "
                f"{line['product_name_snapshot']} "
                "before confirmation."
            )

        cur.execute(
            """
            SELECT
                inventory_item_id,
                quantity_per_batch
            FROM recipe_ingredients
            WHERE recipe_id = %s
            """,
            (line["recipe_id"],),
        )

        ingredients = cur.fetchall()

        if not ingredients:
            raise ValueError(
                f"Recipe for {line['product_name_snapshot']} "
                "has no ingredients."
            )

        for ingredient in ingredients:

            # Allocate recipe consumption
            # proportionally to ordered pieces.
            raw = (
                Decimal(str(ingredient["quantity_per_batch"]))
                * Decimal(str(line["quantity"]))
                / Decimal(str(line["yield_pieces"]))
            )

            used = raw.quantize(
                Decimal("0.001"),
                rounding=ROUND_UP,
            )

            item_id = ingredient["inventory_item_id"]

            required[item_id] = (
                required.get(item_id, Decimal("0"))
                + used
            )

    # Lock inventory rows in consistent order.
    for item_id in sorted(required):

        cur.execute(
            """
            SELECT
                id,
                item_name,
                quantity_on_hand
            FROM inventory_items
            WHERE id = %s
              AND is_active = 1
            FOR UPDATE
            """,
            (item_id,),
        )

        item = cur.fetchone()

        if not item:
            raise ValueError(
                f"Inventory item #{item_id} "
                "is missing or inactive."
            )

        before = Decimal(
            str(item["quantity_on_hand"])
        )

        used = required[item_id]

        if before < used:
            raise ValueError(
                f"Insufficient {item['item_name']}: "
                f"need {used}, available {before}."
            )

        after = before - used

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
                reference_type,
                reference_id,
                notes,
                recorded_by
            )
            VALUES
            (
                %s, 'production_use',
                %s, %s, %s,
                'order_recipe', %s, %s, %s
            )
            """,
            (
                item_id,
                -used,
                before,
                after,
                order_id,
                "Theoretical recipe usage "
                "upon order confirmation",
                actor_id,
            ),
        )

    return len(required)
