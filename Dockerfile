FROM python:3.11-slim

# Install system dependencies for PDF/OCR processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source code
COPY src/ /app/src/
COPY pyproject.toml /app/

# Install package (production only — no dev dependencies in container)
RUN pip install --no-cache-dir -e .

# Create non-root user and data directory
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

USER appuser

# Expose port
EXPOSE 3000

# Health check — allows Docker/orchestrators to detect unhealthy containers
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/health')" || exit 1

# Run HTTP server
CMD ["python", "-m", "document_logic_mcp", "--http"]
