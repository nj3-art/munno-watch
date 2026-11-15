from pathlib import Path
from typing import Optional

from flask import Flask

from .config import Config
from .database import close_db
from .extensions import csrf


def create_app(test_config: Optional[dict] = None) -> Flask:
    project_root = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    csrf.init_app(app)
    app.teardown_appcontext(close_db)

    from .routes import main

    app.register_blueprint(main)
    return app
