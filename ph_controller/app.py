"""
app.py -- Flask application factory.
Run: python3 app.py   then open http://<pi-ip>:8080
"""

from flask import Flask
from routes.dashboard    import bp as dashboard_bp
from routes.config_routes import bp as config_bp
from routes.pump_routes  import bp as pump_bp

app = Flask(__name__)
app.register_blueprint(dashboard_bp)
app.register_blueprint(config_bp)
app.register_blueprint(pump_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)