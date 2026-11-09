
from flask import Blueprint

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/")
def analytics():
    return "Business Analytics Dashboard"
