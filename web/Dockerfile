FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create necessary directories
RUN mkdir -p data/regulatory data/pharmacovigilance processed_data logs

# Set environment variables
# ENV FLASK_APP=app.py # Not needed when specifying app to Gunicorn
ENV FLASK_ENV=production
ENV PORT=5000

# Expose the port
EXPOSE 5000

# Run the application using the correct module path
CMD gunicorn --bind 0.0.0.0:$PORT web.api.app:app
