
from flask import Blueprint, redirect, url_for
from MyFlaskApp.auth.auth_bp import role_required

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.get("/")
@role_required("admin")
def inventory():
    """
    Reuse the existing InventoryPro stock-control page.
    Do not create a second inventory system.
    """
    return redirect(url_for("admin.admin_inventory"))
