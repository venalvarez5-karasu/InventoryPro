
from flask import Blueprint

inventory_bp = Blueprint("inventory", __name__)

@inventory_bp.route("/")
def inventory():
    return "Inventory Management"
