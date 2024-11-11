from flask import Flask, request
import logging
import sys
import os

# Set up root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    stream=sys.stdout  # Explicitly log to stdout
)
logger = logging.getLogger('deploy')
logger.setLevel(logging.DEBUG)

# Create Flask app
app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)  # Set Flask logger to DEBUG level

@app.before_first_request
def before_first_request():
    logger.info("First request received")

@app.before_request
def before_request():
    logger.debug(f"Request received: {request.method} {request.path}")

@app.route('/')
def home():
    logger.info("Home endpoint accessed")
    return "Bot is alive"

@app.route('/_ah/warmup')
def warmup():
    logger.info("Warmup request received")
    return '', 200

@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"An error occurred: {str(error)}", exc_info=True)
    return str(error), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)