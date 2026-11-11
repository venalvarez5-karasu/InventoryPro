
from flask import (
    Blueprint, abort, render_template_string,
    request, url_for
)
from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import (
    current_user, role_required
)
from MyFlaskApp.staff.staff_bp import profile

staff_extras_bp = Blueprint("staff_extras", __name__)

PER_PAGE = 15


def db_one(sql, args=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        cur.close()


def db_all(sql, args=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


def require_staff(kind):
    user = current_user()
    info = profile(user)

    if not info or not info["is_enabled"]:
        abort(403)

    if info["staff_type"] != kind:
        abort(403)

    return user


def pagination(total):
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), pages)

    return page, pages, (page - 1) * PER_PAGE


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} | InventoryPro</title>
<style>
* {box-sizing:border-box}
body {
    margin:0;
    background:#faf9fc;
    color:#30243d;
    font-family:'Segoe UI',Arial,sans-serif;
}
.layout {
    display:grid;
    grid-template-columns:220px minmax(0,1fr);
    min-height:100vh;
}
.sidebar {
    background:#39214e;
    color:#fff;
    padding:28px 15px;
}
.brand {
    font-size:20px;
    font-weight:700;
}
.brand small {
    display:block;
    font-size:11px;
    color:#d9c8e6;
    font-weight:400;
    margin-top:5px;
}
nav {margin-top:35px}
nav a {
    display:block;
    padding:13px;
    margin:5px 0;
    border-radius:8px;
    color:#f1eaf6;
    font-size:13px;
    text-decoration:none;
}
nav a:hover,nav a.active {
    background:#71518e;
}
main {
    padding:30px;
    min-width:0;
}
h1 {
    font-size:26px;
    margin:0 0 7px;
}
.subtitle {
    color:#81748b;
    font-size:13px;
    margin:0 0 25px;
}
.stats {
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:13px;
    margin-bottom:22px;
}
.stat,.panel {
    background:#fff;
    border:1px solid #e9e1ef;
    border-radius:12px;
}
.stat {padding:20px}
.stat span {
    color:#746681;
    font-size:12px;
}
.stat strong {
    display:block;
    color:#39214e;
    font-size:27px;
    margin-top:10px;
}
.panel {
    padding:21px;
    margin-bottom:20px;
}
.panel h2 {
    font-size:17px;
    margin:0 0 18px;
}
.filters {
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-bottom:18px;
}
.filters a,.page-btn {
    padding:9px 13px;
    border:1px solid #e4d7ed;
    border-radius:8px;
    font-size:12px;
    color:#61467b;
    text-decoration:none;
}
.filters a.active {
    background:#76518e;
    border-color:#76518e;
    color:#fff;
}
.table-wrap {overflow-x:auto}
table {
    width:100%;
    min-width:720px;
    border-collapse:collapse;
}
th,td {
    text-align:left;
    padding:14px 12px;
    border-bottom:1px solid #eee8f2;
    font-size:12px;
    vertical-align:middle;
}
th {
    background:#f8f5fb;
    color:#746681;
}
td small {
    display:block;
    color:#877b90;
    margin-top:5px;
}
.status {
    display:inline-block;
    padding:7px 10px;
    border-radius:20px;
    background:#f0e8f7;
    color:#684787;
    font-size:11px;
}
.btn {
    border:0;
    background:#76518e;
    color:white;
    padding:10px 13px;
    border-radius:7px;
    font-size:12px;
    font-weight:600;
    cursor:pointer;
}
.btn:hover {background:#5c3b75}
.action-form {
    display:flex;
    flex-direction:column;
    gap:7px;
}
select {
    width:100%;
    padding:9px;
    border:1px solid #ded3e7;
    border-radius:7px;
    background:#fff;
}
.pager {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    flex-wrap:wrap;
    margin-top:20px;
}
.pager-links {
    display:flex;
    gap:8px;
}
.empty {
    text-align:center;
    color:#84768d;
    padding:25px;
}
@media(max-width:900px) {
    .stats {grid-template-columns:repeat(2,1fr)}
}
@media(max-width:700px) {
    .layout {display:block}
    .sidebar {padding:18px}
    nav {margin-top:15px}
    main {padding:18px}
}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
    <div class="brand">
        InventoryPro
        <small>Tali's Bread &amp; Pastries</small>
    </div>
    <nav>
        <a href="{{ url_for('staff.dashboard') }}">
            Main Dashboard
        </a>
        {% if role == 'bakery' %}
        <a href="{{ url_for('staff_extras.queue') }}"
           class="{{ 'active' if page_type == 'queue' else '' }}">
            Order Queue
        </a>
        {% else %}
        <a href="{{ url_for('staff_extras.history') }}"
           class="{{ 'active' if page_type == 'history' else '' }}">
            Delivery History
        </a>
        {% endif %}
    </nav>
</aside>

<main>
<h1>{{ title }}</h1>
<p class="subtitle">{{ subtitle }}</p>

{% if page_type == 'queue' %}
<section class="stats">
    <div class="stat">
        <span>Awaiting Review</span>
        <strong>{{ stats.review }}</strong>
    </div>
    <div class="stat">
        <span>Confirmed</span>
        <strong>{{ stats.confirmed }}</strong>
    </div>
    <div class="stat">
        <span>Preparing</span>
        <strong>{{ stats.preparing }}</strong>
    </div>
    <div class="stat">
        <span>Ready</span>
        <strong>{{ stats.ready }}</strong>
    </div>
</section>

<section class="panel">
<h2>Customer Orders</h2>

<div class="filters">
{% for value,label in [
    ('all','All'),
    ('pending_verification','For Review'),
    ('pending','New'),
    ('confirmed','Confirmed'),
    ('preparing','Preparing'),
    ('ready','Ready')
] %}
<a href="{{ url_for('staff_extras.queue',status=value) }}"
   class="{{ 'active' if selected == value else '' }}">
    {{ label }}
</a>
{% endfor %}
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
<th>Order</th>
<th>Customer</th>
<th>Amount</th>
<th>Status</th>
<th>Action</th>
</tr>
</thead>
<tbody>
{% for o in rows %}
<tr>
<td>
<strong>{{ o.order_number }}</strong>
<small>{{ o.order_type|title }}</small>
</td>
<td>{{ o.recipient_name or 'Customer' }}</td>
<td>₱{{ "%.2f"|format(o.total_amount) }}</td>
<td>
<span class="status">
{{ o.status|replace('_',' ')|title }}
</span>
</td>
<td>
{% set next_status = {
    'pending_verification':'pending',
    'pending':'confirmed',
    'confirmed':'preparing',
    'preparing':'ready'
}.get(o.status) %}

{% if next_status %}
<form class="action-form"
      method="post"
      action="{{ url_for('staff.change_status',order_id=o.id) }}"
      onsubmit="return confirm('Continue with this order action?')">
<input type="hidden" name="csrf_token"
       value="{{ csrf_token() }}">
<input type="hidden" name="status"
       value="{{ next_status }}">
<button class="btn" type="submit">
{{ {
    'pending':'Mark Reviewed',
    'confirmed':'Accept Order',
    'preparing':'Start Preparing',
    'ready':'Mark Ready'
}.get(next_status) }}
</button>
</form>

{% elif o.status == 'ready'
         and o.order_type == 'delivery' %}
<form class="action-form"
      method="post"
      action="{{ url_for('staff.bakery_assign_rider',order_id=o.id) }}"
      onsubmit="return confirm('Assign selected rider?')">
<input type="hidden" name="csrf_token"
       value="{{ csrf_token() }}">
<select name="rider_id" required>
<option value="">Select Rider</option>
{% for rider in riders %}
<option value="{{ rider.id }}"
    {% if o.rider_user_id == rider.id %}selected{% endif %}>
    {{ rider.first_name }} {{ rider.last_name }}
</option>
{% endfor %}
</select>
<button class="btn" type="submit">
    {{ 'Change Rider' if o.rider_user_id else 'Assign Rider' }}
</button>
</form>

{% elif o.status == 'ready'
         and o.order_type == 'pickup' %}
<form class="action-form"
      method="post"
      action="{{ url_for('staff.change_status',order_id=o.id) }}"
      onsubmit="return confirm('Complete this pickup order?')">
<input type="hidden" name="csrf_token"
       value="{{ csrf_token() }}">
<input type="hidden" name="status"
       value="completed">
<button class="btn" type="submit">Complete Pickup</button>
</form>

{% else %}
<span class="status">No action</span>
{% endif %}
</td>
</tr>
{% else %}
<tr><td colspan="5" class="empty">No orders found.</td></tr>
{% endfor %}
</tbody>
</table>
</div>

<div class="pager">
<span>{{ total }} orders · Page {{ page }} of {{ pages }}</span>
<div class="pager-links">
{% if page > 1 %}
<a class="page-btn"
   href="{{ url_for('staff_extras.queue',
                    status=selected,page=page-1) }}">
    Previous
</a>
{% endif %}
{% if page < pages %}
<a class="page-btn"
   href="{{ url_for('staff_extras.queue',
                    status=selected,page=page+1) }}">
    Next
</a>
{% endif %}
</div>
</div>
</section>

{% else %}

<section class="stats">
<div class="stat">
    <span>Completed Deliveries</span>
    <strong>{{ total }}</strong>
</div>
</section>

<section class="panel">
<h2>My Delivery Records</h2>
<div class="table-wrap">
<table>
<thead>
<tr>
<th>Order</th>
<th>Customer</th>
<th>Destination</th>
<th>Amount</th>
<th>Ordered On</th>
</tr>
</thead>
<tbody>
{% for o in rows %}
<tr>
<td><strong>{{ o.order_number }}</strong></td>
<td>{{ o.recipient_name or 'Customer' }}</td>
<td>{{ o.delivery_address_snapshot or 'N/A' }}</td>
<td>₱{{ "%.2f"|format(o.total_amount) }}</td>
<td>{{ o.created_at }}</td>
</tr>
{% else %}
<tr><td colspan="5" class="empty">
No completed deliveries yet.
</td></tr>
{% endfor %}
</tbody>
</table>
</div>

<div class="pager">
<span>Page {{ page }} of {{ pages }}</span>
<div class="pager-links">
{% if page > 1 %}
<a class="page-btn"
   href="{{ url_for('staff_extras.history',page=page-1) }}">
    Previous
</a>
{% endif %}
{% if page < pages %}
<a class="page-btn"
   href="{{ url_for('staff_extras.history',page=page+1) }}">
    Next
</a>
{% endif %}
</div>
</div>
</section>
{% endif %}
</main>
</div>
</body>
</html>
"""


@staff_extras_bp.get("/queue")
@role_required("staff")
def queue():
    require_staff("bakery")

    statuses = (
        "pending_verification",
        "pending",
        "confirmed",
        "preparing",
        "ready",
    )

    selected = request.args.get("status", "all")

    if selected not in statuses + ("all",):
        selected = "all"

    stats = db_one("""
        SELECT
          COALESCE(SUM(status IN
            ('pending_verification','pending')),0) AS review,
          COALESCE(SUM(status='confirmed'),0) AS confirmed,
          COALESCE(SUM(status='preparing'),0) AS preparing,
          COALESCE(SUM(status='ready'),0) AS ready
        FROM orders
    """)

    if selected == "all":
        where = """
            o.status IN (
                'pending_verification','pending',
                'confirmed','preparing','ready'
            )
        """
        args = []
    else:
        where = "o.status = %s"
        args = [selected]

    total = int(db_one(
        "SELECT COUNT(*) AS total FROM orders o WHERE " + where,
        tuple(args)
    )["total"])

    page, pages, offset = pagination(total)

    orders = db_all("""
        SELECT
            o.id, o.order_number, o.order_type,
            o.status, o.recipient_name, o.total_amount,
            d.rider_user_id
        FROM orders o
        LEFT JOIN delivery_assignments d
            ON d.order_id = o.id
        WHERE """ + where + """
        ORDER BY o.created_at ASC, o.id ASC
        LIMIT %s OFFSET %s
    """, tuple(args + [PER_PAGE, offset]))

    riders = db_all("""
        SELECT u.id, u.first_name, u.last_name
        FROM users u
        JOIN staff_profiles sp ON sp.user_id = u.id
        WHERE u.role = 'staff'
          AND u.account_status = 'active'
          AND sp.staff_type = 'rider'
          AND sp.is_enabled = 1
        ORDER BY u.first_name, u.last_name
    """)

    return render_template_string(
        PAGE,
        title="Bakery Order Queue",
        subtitle="Review and manage customer orders.",
        page_type="queue",
        role="bakery",
        stats=stats,
        selected=selected,
        rows=orders,
        riders=riders,
        total=total,
        page=page,
        pages=pages
    )


@staff_extras_bp.get("/history")
@role_required("staff")
def history():
    user = require_staff("rider")

    total = int(db_one("""
        SELECT COUNT(*) AS total
        FROM orders o
        JOIN delivery_assignments d
            ON d.order_id = o.id
        WHERE d.rider_user_id = %s
          AND o.order_type = 'delivery'
          AND o.status = 'completed'
    """, (user["id"],))["total"])

    page, pages, offset = pagination(total)

    orders = db_all("""
        SELECT
            o.order_number,
            o.recipient_name,
            o.delivery_address_snapshot,
            o.total_amount,
            o.created_at
        FROM orders o
        JOIN delivery_assignments d
            ON d.order_id = o.id
        WHERE d.rider_user_id = %s
          AND o.order_type = 'delivery'
          AND o.status = 'completed'
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT %s OFFSET %s
    """, (user["id"], PER_PAGE, offset))

    return render_template_string(
        PAGE,
        title="Delivery History",
        subtitle="Your completed delivery records.",
        page_type="history",
        role="rider",
        rows=orders,
        total=total,
        page=page,
        pages=pages
    )
