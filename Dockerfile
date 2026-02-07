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

# Install package with dev dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Create non-root user and data directory
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

USER appuser

# Expose port
EXPOSE 3000

# Run HTTP server
CMD ["python", "-m", "document_logic_mcp", "--http"]
