FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install essential system dependencies
# gcc: Required for compiling Python packages with C extensions (e.g., psycopg2)
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Expose port
EXPOSE 8098

# Health check using Python requests (no external tools needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8098/health', timeout=5)" || exit 1

# Run application
CMD sh -c 'uvicorn app.transport.http_app_secure:app --host 0.0.0.0 --port ${PORT:-8098} --log-level info'

