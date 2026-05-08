FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p screenshots

CMD ["python", "app.py"]
