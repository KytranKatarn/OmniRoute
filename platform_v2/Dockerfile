FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Docker CLI for sandbox management
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    git \
    curl \
    && curl -fsSL https://get.docker.com -o get-docker.sh \
    && sh get-docker.sh \
    && rm get-docker.sh \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create templates directory
RUN mkdir -p templates

# Expose port
EXPOSE 3000

# Run application
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "2", "--timeout", "300", "app:app"]
