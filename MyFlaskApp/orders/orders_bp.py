
from flask import Blueprint

orders_bp = Blueprint("orders", __name__)

@orders_bp.route("/")
def orders():
    return "Order Management"
