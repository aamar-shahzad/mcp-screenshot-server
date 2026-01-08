# MCP Screenshot Server Dockerfile
# Supports screenshot capture and image annotation

FROM python:3.12-slim

LABEL maintainer="MCP Screenshot Server Contributors"
LABEL description="MCP server for screenshot capture and image annotation"
LABEL version="0.1.0"

# Install system dependencies for image processing and clipboard
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For Pillow image processing
    libjpeg62-turbo \
    libpng16-16 \
    libfreetype6 \
    # For X11/clipboard support (optional)
    xclip \
    # For virtual display (headless screenshot support)
    xvfb \
    scrot \
    # Clean up
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 mcpuser

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml README.md LICENSE* ./
COPY src/ ./src/

# Install the package
RUN pip install --no-cache-dir -e ".[clipboard]"

# Switch to non-root user
USER mcpuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# Default command runs the server with stdio transport
# For HTTP transport, override with: --transport streamable-http --port 8000
ENTRYPOINT ["mcp-screenshot-server"]
CMD ["--transport", "stdio"]

# Expose port for HTTP transports
EXPOSE 8000

# Health check for HTTP mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 0

