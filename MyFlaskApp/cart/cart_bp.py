
from flask import Blueprint

cart_bp = Blueprint("cart", __name__)

@cart_bp.route("/")
def cart():
    return "Customer Shopping Cart"

@cart_bp.route("/checkout")
def checkout():
    return "Customer Checkout"
