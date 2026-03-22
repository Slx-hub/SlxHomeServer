FROM python:3.12-alpine

# Docker CLI is needed for compose commands
RUN apk add --no-cache docker-cli docker-cli-compose

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app.py .
COPY frontend/ /app/static/

EXPOSE 50001

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "50001"]
