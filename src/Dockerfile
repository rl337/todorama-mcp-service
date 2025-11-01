FROM python:3.11-alpine

# Install system dependencies
RUN apk add --no-cache \
    sqlite \
    gzip \
    && rm -rf /var/cache/apk/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ .

# Create data directory
RUN mkdir -p /app/data /app/backups && \
    chmod 755 /app/data /app/backups

# Non-root user for security
RUN adduser -D -s /bin/sh todo && \
    chown -R todo:todo /app

USER todo

# Expose HTTP port
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:8004/health || exit 1

# Environment variables
ENV TODO_DB_PATH=/app/data/todos.db
ENV TODO_BACKUPS_DIR=/app/backups
ENV TODO_SERVICE_PORT=8004
ENV TODO_BACKUP_INTERVAL_HOURS=24

# Run the service
CMD ["python", "main.py"]
