
from flask import Flask
from threading import Thread
import os
import logging

app = Flask('')
logging.basicConfig(level=logging.INFO)

@app.route('/')
def home():
    return "Bot is alive"

@app.route('/health')
def health():
    return "OK", 200

def run():
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    server = Thread(target=run, daemon=True)
    server.start()
    logging.info("Keep alive server started")
