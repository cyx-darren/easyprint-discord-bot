#!/bin/bash

# Exit on error
set -e

# Install packages using pip
python3 -m pip install --user --no-cache-dir -r requirements.txt

# Make main.py executable
chmod +x main.py

# Run the bot
python3 main.py