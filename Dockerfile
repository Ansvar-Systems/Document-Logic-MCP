FROM python:3.11-slim

# Install system dependencies for PDF/OCR processing
RUN apt-get update && apt-get install -y \
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
RUN pip install -e ".[dev]"

# Create data directory
RUN mkdir -p /app/data

# Run MCP server
CMD ["python", "-m", "document_logic_mcp.server"]
