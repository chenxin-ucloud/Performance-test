"""Center service Flask application entry point."""
from flask import Flask

from models import db
from routes.api import api_bp
import config


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config)
    app.register_blueprint(api_bp)
    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.CENTER_HOST, port=config.CENTER_PORT, debug=config.DEBUG, threaded=True)
