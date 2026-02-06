# Dockerfile for ITSM Teams Bot Orchestrator
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system CA tools and update trust store
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/*

# Trust corporate CA (optional; only if file exists in build context)
RUN if [ -d "certs" ] && [ "$(ls -A certs/*.crt 2>/dev/null)" ]; then \
    cp certs/*.crt /usr/local/share/ca-certificates/ && \
    update-ca-certificates; \
    fi || true

# Ensure Python tooling uses system bundle
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code

# Copy application code
COPY src/ ./src/
COPY knowledge-bases/ ./knowledge-bases/

# Expose port
EXPOSE 3978

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=3978
# Fix import paths by adding src to PYTHONPATH
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Health check (no curl dependency)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:%s/' % __import__('os').environ.get('PORT','3978'))" || exit 1
CMD ["python", "src/teams_server.py"]
