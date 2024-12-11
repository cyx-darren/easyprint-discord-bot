
from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
