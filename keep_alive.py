from flask import Flask
from threading import Thread
import os

def keep_alive():
    app = Flask('')

    @app.route('/')
    def home():
        return "Bot is alive"

    def run():
        app.run(host='0.0.0.0', port=8080)

    t = Thread(target=run, daemon=True)
    t.start()