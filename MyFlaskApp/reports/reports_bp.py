
from flask import Blueprint, redirect, url_for
from MyFlaskApp.auth.auth_bp import role_required

reports_bp = Blueprint("reports", __name__)


@reports_bp.get("/")
@role_required("admin")
def reports():
    """
    Open the existing InventoryPro reporting console.
    Existing CSV export functionality is preserved.
    """
    return redirect(url_for("admin.admin_reports"))
