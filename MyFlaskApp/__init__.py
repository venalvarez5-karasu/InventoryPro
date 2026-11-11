import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask
from flask_mysqldb import MySQL
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

mysql = MySQL()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)
csrf = CSRFProtect()

def reg_app():
    env_path = (Path(__file__).resolve().parent.parent / ".env")
    load_dotenv(env_path)
    app = Flask(__name__)
    limiter.init_app(app)
    csrf.init_app(app)

    app.secret_key = "akoto123"

    if not app.secret_key:
        raise RuntimeError("SECRET_KEY is missing in .env")

    # Session Configuration
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"]   = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    # MySQL Configuration
    app.config["MYSQL_HOST"] = "localhost"
    app.config["MYSQL_USER"] =  "root"
    app.config["MYSQL_PASSWORD"] = ""
    app.config["MYSQL_DB"] = "inventorypro_db"

    mysql.init_app(app)

    app.config["MAIL_SERVER"]   = "smtp.gmail.com"
    app.config["MAIL_PORT"]     = 587
    app.config["MAIL_USE_TLS"]  = True
    app.config["MAIL_USERNAME"] = "zyonley28@gmail.com"
    app.config["MAIL_PASSWORD"] = "qzlv tzwu pbgg mkjh"
    mail.init_app(app)

    # Import Blueprints
    from .admin.admin_bp import admin_bp
    from .analytics.analytics_bp import analytics_bp
    from .auth.auth_bp import auth_bp
    from .cart.cart_bp import cart_bp
    from .index.index_bp import index_bp
    from .inventory.inventory_bp import inventory_bp
    from .orders.orders_bp import orders_bp
    from .production.production_bp import production_bp
    from .products.products_bp import products_bp
    from .reports.reports_bp import reports_bp
    from .staff.staff_bp import staff_bp

    # Register Blueprints
    app.register_blueprint(index_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(cart_bp, url_prefix="/cart")
    app.register_blueprint(products_bp, url_prefix="/products")
    app.register_blueprint(orders_bp, url_prefix="/orders")

    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(analytics_bp, url_prefix="/admin/analytics")
    app.register_blueprint(inventory_bp, url_prefix="/admin/inventory")
    app.register_blueprint(production_bp, url_prefix="/admin/production")
    app.register_blueprint(reports_bp, url_prefix="/admin/reports")
    app.register_blueprint(staff_bp, url_prefix="/staff")

    return app
