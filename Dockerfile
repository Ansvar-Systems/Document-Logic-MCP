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

# Install package (without sentence-transformers/torch — embeddings are lazy-loaded
# and will gracefully degrade if unavailable)
RUN pip install --no-cache-dir --timeout 120 \
    mcp anthropic pdfplumber python-docx pytesseract Pillow \
    aiosqlite fastapi "uvicorn[standard]" numpy \
    openpyxl python-pptx beautifulsoup4 pdf2image \
    && pip install --no-cache-dir --no-deps -e .

# Create non-root user and data directory
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data

USER appuser

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/health', timeout=2).read()"

# Run HTTP server
CMD ["python", "-m", "document_logic_mcp", "--http"]
