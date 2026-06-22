"""Agent Flask application entry point."""
from flask import Flask

from routes.agent_api import agent_api_bp
import config


def create_app():
    app = Flask(__name__)
    app.register_blueprint(agent_api_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=config.AGENT_HOST, port=config.AGENT_PORT, threaded=True)
