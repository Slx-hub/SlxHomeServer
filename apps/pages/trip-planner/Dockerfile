FROM python:3.12-alpine

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app.py .
COPY backend/agent_skill.md .
COPY frontend/ /app/static/

EXPOSE 50004

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "50004"]
