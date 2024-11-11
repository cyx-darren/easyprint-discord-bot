import os
import sys
import logging
import logging.config

# Load logging configuration
logging.config.fileConfig('logging.conf')

# Gunicorn config
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
workers = 1
timeout = 120
accesslog = '-'
errorlog = '-'
capture_output = True
enable_stdio_inheritance = True

def on_starting(server):
    logger = logging.getLogger('gunicorn.error')
    logger.info('Starting Gunicorn server...')

def on_exit(server):
    logger = logging.getLogger('gunicorn.error')
    logger.info('Shutting down Gunicorn server...')

def post_worker_init(worker):
    logger = logging.getLogger('gunicorn.error')
    logger.info(f'Worker {worker.pid} initialized')