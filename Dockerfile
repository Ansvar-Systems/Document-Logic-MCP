FROM python:3.11-slim

# Install system dependencies for PDF/OCR processing
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libpoppler-cpp-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ /app/src/
COPY pyproject.toml /app/

# Install package
RUN pip install -e .

# Create data directory
RUN mkdir -p /app/data

# Run MCP server
CMD ["python", "-m", "src.document_logic_mcp.server"]
