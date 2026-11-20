import os
import threading

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "main.login"


def create_app(config_object="config.Config", start_poller=True):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    from . import models  # noqa: F401
    from .views import bp
    from .cli import register_cli
    from .utils import money

    app.register_blueprint(bp)
    register_cli(app)
    app.jinja_env.filters["money"] = money

    with app.app_context():
        db.create_all()
        models.ensure_admin(app)

    if start_poller and app.config["MOMO_MODE"] != "off" and not app.config.get("TESTING"):
        from .payments import poll_pending_forever

        threading.Thread(target=poll_pending_forever, args=(app,), daemon=True).start()
    return app
