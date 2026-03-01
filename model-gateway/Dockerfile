FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 11435
ENV OPENAI_COMPAT_PORT=11435
USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "11435"]
