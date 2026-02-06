# Dockerfile for ITSM Teams Bot Orchestrator
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY knowledge-bases/ ./knowledge-bases/

# Expose port
EXPOSE 3978

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=3978

# Health check (no curl dependency)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:%s/' % __import__('os').environ.get('PORT','3978'))" || exit 1

# Run the Teams server
CMD ["python", "src/teams_server.py"]
