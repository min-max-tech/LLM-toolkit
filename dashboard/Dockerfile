FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

EXPOSE 8080
USER appuser
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
