
from flask import Blueprint

production_bp = Blueprint("production", __name__)

@production_bp.route("/")
def production():
    return "Recipes and Production Management"
