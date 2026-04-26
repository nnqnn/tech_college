FROM python:3.12-slim

WORKDIR /app

COPY app.py init.sql ./

ENV DB_PATH=/app/data/store.db

CMD ["python", "app.py"]
