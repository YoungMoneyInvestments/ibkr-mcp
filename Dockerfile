FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e .

# Environment variables with defaults
ENV IBKR_HOST=127.0.0.1
ENV IBKR_PORT=7497
ENV IBKR_CLIENT_ID=1
ENV IBKR_READONLY=false
ENV MCP_TRANSPORT=stdio

# Run the server
ENTRYPOINT ["ibkr-mcp"]
CMD []
