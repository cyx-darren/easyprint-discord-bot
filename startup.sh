#!/bin/bash

echo "Starting deployment process..."
echo "Current directory: $(pwd)"
echo "Python version: $(python3 --version)"
echo "Installing requirements..."
python3 -m pip install --user flask gunicorn
echo "Starting server..."
exec gunicorn --log-level debug --access-logfile - --error-logfile - deploy:app