FROM python:3.10-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir flask discord.py google-auth google-auth-oauthlib google-api-python-client pytz aiohttp gunicorn

EXPOSE 8080

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 keep_alive:app