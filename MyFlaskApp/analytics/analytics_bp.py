
from flask import Blueprint, render_template_string
from MySQLdb.cursors import DictCursor

from MyFlaskApp import mysql
from MyFlaskApp.auth.auth_bp import role_required

analytics_bp = Blueprint("analytics", __name__)


def query_one(sql, params=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def query_all(sql, params=()):
    cur = mysql.connection.cursor(DictCursor)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


@analytics_bp.get("/")
@role_required("admin")
def analytics():
    overview = query_one("""
        SELECT
            COUNT(*) AS total_orders,
            COALESCE(SUM(status = 'completed'), 0)
                AS completed_orders,
            COALESCE(SUM(status = 'pending'), 0)
                AS pending_orders,
            COALESCE(SUM(
                CASE WHEN status = 'completed'
                THEN total_amount ELSE 0 END
            ), 0) AS completed_sales
        FROM orders
    """)

    top_products = query_all("""
        SELECT
            oi.product_name_snapshot AS name,
            SUM(oi.quantity) AS quantity,
            SUM(oi.line_total) AS amount
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        WHERE o.status = 'completed'
        GROUP BY oi.product_name_snapshot
        ORDER BY quantity DESC
        LIMIT 5
    """)

    daily = query_all("""
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS order_count,
            COALESCE(SUM(
                CASE WHEN status = 'completed'
                THEN total_amount ELSE 0 END
            ), 0) AS sales
        FROM orders
        WHERE created_at >= CURDATE() - INTERVAL 6 DAY
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """)

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block content %}
    <style>
      .analytics-grid {
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:14px;
        margin:20px 0;
      }
      .analytics-card,.analytics-panel {
        background:#fff;
        border:1px solid #e9e1ee;
        border-radius:12px;
        padding:22px;
      }
      .analytics-card span {
        font-size:12px;
        color:#766780;
        display:block;
      }
      .analytics-card strong {
        display:block;
        font-size:27px;
        color:#3e2851;
        margin-top:10px;
      }
      .analytics-panel { margin-top:18px; }
      .analytics-panel h2 {
        font-size:17px;
        color:#382449;
        margin:0 0 18px;
      }
      .analytics-table {
        width:100%;
        border-collapse:collapse;
      }
      .analytics-table th,
      .analytics-table td {
        text-align:left;
        padding:12px;
        border-bottom:1px solid #eee8f2;
        font-size:13px;
      }
      .analytics-table th {background:#f8f5fb;}
      .analytics-bar {
        height:9px;
        background:#eee6f4;
        border-radius:20px;
        overflow:hidden;
      }
      .analytics-fill {
        height:100%;
        background:#78549a;
        border-radius:20px;
      }
      @media(max-width:900px) {
        .analytics-grid {
          grid-template-columns:repeat(2,minmax(0,1fr));
        }
      }
      @media(max-width:480px) {
        .analytics-grid {grid-template-columns:1fr;}
      }
    </style>

    <div class="adm-page-heading">
      <div>
        <span class="adm-eyebrow">BUSINESS INTELLIGENCE</span>
        <h1>Analytics Dashboard</h1>
        <p>Sales performance and bakery order activity.</p>
      </div>
    </div>

    <div class="analytics-grid">
      <div class="analytics-card">
        <span>Total Orders</span>
        <strong>{{ overview.total_orders }}</strong>
      </div>
      <div class="analytics-card">
        <span>Completed Orders</span>
        <strong>{{ overview.completed_orders }}</strong>
      </div>
      <div class="analytics-card">
        <span>Pending Orders</span>
        <strong>{{ overview.pending_orders }}</strong>
      </div>
      <div class="analytics-card">
        <span>Completed Order Value</span>
        <strong>
          ₱{{ "%.2f"|format(overview.completed_sales) }}
        </strong>
      </div>
    </div>

    <section class="analytics-panel">
      <h2>Daily Orders — Last 7 Days</h2>
      <table class="analytics-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Orders</th>
            <th>Completed Value</th>
          </tr>
        </thead>
        <tbody>
          {% for row in daily %}
          <tr>
            <td>{{ row.day }}</td>
            <td>{{ row.order_count }}</td>
            <td>₱{{ "%.2f"|format(row.sales) }}</td>
          </tr>
          {% else %}
          <tr><td colspan="3">No recent orders.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </section>

    <section class="analytics-panel">
      <h2>Top Selling Products</h2>
      {% set max_qty = top_products[0].quantity
          if top_products else 1 %}
      {% for product in top_products %}
      <div style="margin-bottom:18px">
        <div style="display:flex;justify-content:space-between;
                    margin-bottom:8px;font-size:13px">
          <strong>{{ product.name }}</strong>
          <span>{{ product.quantity }} sold</span>
        </div>
        <div class="analytics-bar">
          <div class="analytics-fill"
            style="width:{{ (product.quantity / max_qty * 100)
                          |round(1) }}%">
          </div>
        </div>
      </div>
      {% else %}
      <p>No completed sales yet.</p>
      {% endfor %}
    </section>
    {% endblock %}
    """,
    title="Analytics",
    overview=overview,
    top_products=top_products,
    daily=daily)
