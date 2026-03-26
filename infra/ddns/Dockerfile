FROM python:3.11-alpine

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY porkbun_updater.py .
COPY config.yaml .

# Run the updater
CMD ["python", "porkbun_updater.py"]
