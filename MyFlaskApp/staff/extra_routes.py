
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


def require_staff_type(staff_type):
    user = current_user()
    staff_profile = profile(user)

    if not staff_profile:
        abort(403)

    if not staff_profile["is_enabled"]:
        abort(403)

    if staff_profile["staff_type"] != staff_type:
        abort(403)

    return user


BASE_STYLE = """
<style>
* { box-sizing:border-box; }
body {
    margin:0;
    font-family:'Segoe UI',Arial,sans-serif;
    background:#faf9fc;
    color:#30243d;
}
.layout {
    display:grid;
    grid-template-columns:210px minmax(0,1fr);
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
    margin-bottom:4px;
}
.brand-sub {
    color:#d8c8e5;
    font-size:11px;
    margin-bottom:38px;
}
.nav-link {
    display:block;
    text-decoration:none;
    color:#f1e9f8;
    padding:13px;
    border-radius:8px;
    font-size:13px;
    margin-bottom:6px;
}
.nav-link:hover,.nav-link.active {
    background:#6e4c8b;
}
.main {padding:30px;min-width:0;}
.header {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    flex-wrap:wrap;
    margin-bottom:24px;
}
h1 {
    font-size:26px;
    margin:0 0 6px;
}
.subtitle {
    color:#817489;
    font-size:13px;
    margin:0;
}
.card {
    background:white;
    border:1px solid #e9e1ef;
    border-radius:12px;
    padding:22px;
    margin-bottom:18px;
}
.stats {
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:12px;
    margin-bottom:22px;
}
.stat {
    background:white;
    padding:20px;
    border:1px solid #e9e1ef;
    border-radius:12px;
}
.stat small {
    color:#75677d;
    font-size:12px;
}
.stat strong {
    display:block;
    font-size:27px;
    margin-top:9px;
    color:#39214e;
}
.table-wrap {overflow-x:auto;}
table {
    width:100%;
    border-collapse:collapse;
    min-width:720px;
}
th,td {
    padding:14px 12px;
    text-align:left;
    font-size:12px;
    border-bottom:1px solid #eee9f1;
    vertical-align:top;
}
th {
    color:#72647c;
    background:#f8f5fb;
    font-weight:700;
}
td small {
    display:block;
    color:#817489;
    margin-top:5px;
    line-height:1.5;
}
.status {
    display:inline-block;
    border-radius:20px;
    background:#f0e8f6;
    color:#644180;
    padding:7px 10px;
    font-size:11px;
    font-weight:600;
}
.btn {
    display:inline-block;
    background:#76518e;
    color:#fff;
    border:none;
    padding:10px 14px;
    border-radius:7px;
    text-decoration:none;
    font:600 12px 'Segoe UI',Arial,sans-serif;
    cursor:pointer;
}
.btn:hover {background:#5a3c75;}
.btn-light {
    background:#f1eaf7;
    color:#56396d;
}
.filters {
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    margin-bottom:18px;
}
.filters a {
    font-size:12px;
    text-decoration:none;
    padding:9px 13px;
    border:1px solid #e5dced;
    border-radius:8px;
    color:#644b75;
}
.filters a.active {
    background:#76518e;
    color:white;
}
.actions {
    display:flex;
    flex-direction:column;
    gap:8px;
    min-width:140px;
}
select {
    width:100%;
    border:1px solid #ded3e6;
    border-radius:7px;
    padding:9px;
    background:#fff;
}
.pagination {
    display:flex;
    align-items:center;
    justify-content:space-between;
    flex-wrap:wrap;
    gap:12px;
    margin-top:18px;
}
.empty {
    padding:25px;
    text-align:center;
    color:#796c84;
}
@media(max-width:900px) {
    .stats {grid-template-columns:repeat(2,1fr);}
}
@media(max-width:700px) {
    .layout {display:block;}
    .sidebar {padding:16px;}
    .brand-sub {margin-bottom:16px;}
    .main {padding:16px;}
    h1 {font-size:22px;}
}
</style>
"""


LAYOUT_START = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} | InventoryPro</title>
""" + BASE_STYLE + """
</head>
<body>
<div class="layout">
<aside class="sidebar">
    <div class="brand">InventoryPro</div>
    <div class="brand-sub">Tali's Bread &amp; Pastries</div>
    <nav>
        <a class="nav-link"
           href="{{ url_for('staff.dashboard') }}">
           Dashboard
        </a>
        <a class="nav-link"
           href="{{ url_for('staff_extras.queue') }}">
           Bakery Order Queue
        </a>
        <a class="nav-link"
           href="{{ url_for('staff_extras.history') }}">
           Rider History
        </a>
    </nav>
</aside>
<main class="main">
<div class="header">
    <div>
        <h1>{{ title }}</h1>
        <p class="subtitle">{{ subtitle }}</p>
    </div>
    <a class="btn btn-light"
       href="{{ url_for('staff.dashboard') }}">
       Back to Dashboard
    </a>
</div>
"""


LAYOUT_END = """
</main>
</div>
</body>
</html>
"""


@staff_extras_bp.get("/history")
@role_required("staff")
def history():
    user = require_staff_type("rider")

    total = int(db_one("""
        SELECT COUNT(*) AS total
        FROM orders o
        JOIN delivery_assignments d ON d.order_id = o.id
        WHERE d.rider_user_id = %s
          AND o.order_type = 'delivery'
          AND o.status = 'completed'
    """, (user["id"],))["total"])

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page = min(page, pages)

    history_rows = db_all("""
        SELECT
            o.order_number,
            o.recipient_name,
            o.delivery_address_snapshot,
            o.total_amount,
            o.status,
            o.created_at
        FROM orders o
        JOIN delivery_assignments d ON d.order_id = o.id
        WHERE d.rider_user_id = %s
          AND o.order_type = 'delivery'
          AND o.status = 'completed'
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT %s OFFSET %s
    """, (
        user["id"],
        PER_PAGE,
        (page - 1) * PER_PAGE
    ))

    html = LAYOUT_START + """
<section class="stats">
    <div class="stat">
        <small>Completed Deliveries</small>
        <strong>{{ total }}</strong>
    </div>
</section>

<section class="card">
    <h2>Delivery Records</h2>
    <div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Delivery Address</th>
                <th>Amount</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
        {% for order in rows %}
            <tr>
                <td><strong>{{ order.order_number }}</strong></td>
                <td>{{ order.recipient_name or 'Customer' }}</td>
                <td>{{ order.delivery_address_snapshot or 'N/A' }}</td>
                <td>₱{{ "%.2f"|format(order.total_amount) }}</td>
                <td><span class="status">Completed</span></td>
            </tr>
        {% else %}
            <tr><td colspan="5" class="empty">
                No completed deliveries yet.
            </td></tr>
        {% endfor %}
        </tbody>
    </table>
    </div>

    <div class="pagination">
        <span>Page {{ page }} of {{ pages }}</span>
        <div>
        {% if page > 1 %}
            <a class="btn btn-light"
               href="{{ url_for('staff_extras.history', page=page-1) }}">
               Previous
            </a>
        {% endif %}
        {% if page < pages %}
            <a class="btn"
               href="{{ url_for('staff_extras.history', page=page+1) }}">
               Next
            </a>
        {% endif %}
        </div>
    </div>
</section>
""" + LAYOUT_END

    return render_template_string(
        html,
        title="Delivery History",
        subtitle="Review your completed deliveries.",
        rows=history_rows,
        total=total,
        page=page,
        pages=pages
    )


@staff_extras_bp.get("/queue")
@role_required("staff")
def queue():
    require_staff_type("bakery")

    allowed = ("pending", "confirmed", "preparing", "ready")
    selected = request.args.get("status", "all")

    if selected not in allowed + ("all",):
        selected = "all"

    where = "status IN ('pending','confirmed','preparing','ready')"
    args = []

    if selected != "all":
        where += " AND status = %s"
        args.append(selected)

    totals = db_one("""
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(status = 'pending'),0) AS pending,
            COALESCE(SUM(status = 'confirmed'),0) AS confirmed,
            COALESCE(SUM(status = 'preparing'),0) AS preparing,
            COALESCE(SUM(status = 'ready'),0) AS ready
        FROM orders
        WHERE status IN ('pending','confirmed','preparing','ready')
    """)

    total = int(db_one(
        "SELECT COUNT(*) AS total FROM orders WHERE " + where,
        tuple(args)
    )["total"])

    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page = min(page, pages)

    orders = db_all("""
        SELECT
            o.id,
            o.order_number,
            o.order_type,
            o.status,
            o.recipient_name,
            o.total_amount,
            d.rider_user_id
        FROM orders o
        LEFT JOIN delivery_assignments d ON d.order_id = o.id
        WHERE """ + where.replace("status", "o.status") + """
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT %s OFFSET %s
    """, tuple(args + [PER_PAGE, (page-1)*PER_PAGE]))

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

    html = LAYOUT_START + """
<div class="stats">
    <div class="stat"><small>New</small>
        <strong>{{ totals.pending }}</strong></div>
    <div class="stat"><small>Confirmed</small>
        <strong>{{ totals.confirmed }}</strong></div>
    <div class="stat"><small>Preparing</small>
        <strong>{{ totals.preparing }}</strong></div>
    <div class="stat"><small>Ready</small>
        <strong>{{ totals.ready }}</strong></div>
</div>

<section class="card">
<h2>Customer Orders</h2>

<div class="filters">
{% for value,label in [
    ('all','All'),('pending','New'),
    ('confirmed','Confirmed'),
    ('preparing','Preparing'),('ready','Ready')
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
{% for order in orders %}
<tr>
<td>
    <strong>{{ order.order_number }}</strong>
    <small>{{ order.order_type|title }}</small>
</td>
<td>{{ order.recipient_name or 'Customer' }}</td>
<td>₱{{ "%.2f"|format(order.total_amount) }}</td>
<td>
    <span class="status">
        {{ order.status|replace('_',' ')|title }}
    </span>
</td>
<td>
<div class="actions">
{% set next_status = {
    'pending':'confirmed',
    'confirmed':'preparing',
    'preparing':'ready'
}.get(order.status) %}

{% if next_status %}
<form method="post"
      action="{{ url_for('staff.change_status',
                         order_id=order.id) }}"
      onsubmit="return confirm('Update order status?')">
    <input type="hidden" name="csrf_token"
           value="{{ csrf_token() }}">
    <input type="hidden" name="status"
           value="{{ next_status }}">
    <button type="submit" class="btn">
        {{ {
          'confirmed':'Confirm Order',
          'preparing':'Start Preparing',
          'ready':'Mark Ready'
        }.get(next_status) }}
    </button>
</form>

{% elif order.status == 'ready'
       and order.order_type == 'delivery' %}

<form method="post"
      action="{{ url_for('staff.bakery_assign_rider',
                         order_id=order.id) }}"
      onsubmit="return confirm('Assign selected rider?')">
    <input type="hidden" name="csrf_token"
           value="{{ csrf_token() }}">
    <select name="rider_id" required>
      <option value="">Select Rider</option>
      {% for rider in riders %}
      <option value="{{ rider.id }}"
        {{ 'selected' if order.rider_user_id == rider.id else '' }}>
        {{ rider.first_name }} {{ rider.last_name }}
      </option>
      {% endfor %}
    </select>
    <button type="submit" class="btn">
        {{ 'Update Rider' if order.rider_user_id
           else 'Assign Rider' }}
    </button>
</form>

{% else %}
    <span class="status">Ready for Pickup</span>
{% endif %}
</div>
</td>
</tr>
{% else %}
<tr><td colspan="5" class="empty">No orders found.</td></tr>
{% endfor %}
</tbody>
</table>
</div>

<div class="pagination">
    <span>{{ total }} orders · Page {{ page }} of {{ pages }}</span>
    <div>
    {% if page > 1 %}
    <a class="btn btn-light"
       href="{{ url_for('staff_extras.queue',
                        status=selected,page=page-1) }}">
       Previous
    </a>
    {% endif %}
    {% if page < pages %}
    <a class="btn"
       href="{{ url_for('staff_extras.queue',
                        status=selected,page=page+1) }}">
       Next
    </a>
    {% endif %}
    </div>
</div>
</section>
""" + LAYOUT_END

    return render_template_string(
        html,
        title="Bakery Order Queue",
        subtitle="Manage customer orders and rider assignments.",
        orders=orders,
        riders=riders,
        totals=totals,
        total=total,
        pages=pages,
        page=page,
        selected=selected
    )
