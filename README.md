# MCP Screenshot Server 📸

A powerful [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for capturing screenshots and annotating images with boxes, lines, arrows, circles, text, and highlights.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![MCP](https://img.shields.io/badge/MCP-compatible-purple.svg)

## Features

- 📷 **Screenshot Capture** - Full screen, region, or window-specific captures
- 📦 **Box Annotation** - Draw rectangles with customizable colors and fill
- ➡️ **Arrow Annotation** - Draw directional arrows with adjustable head sizes
- 📏 **Line Drawing** - Simple line annotations
- ⭕ **Circle/Ellipse** - Draw circles and ellipses
- 📝 **Text Overlay** - Add text with custom fonts and backgrounds
- 🔦 **Highlight Regions** - Semi-transparent highlight overlays
- 💾 **Save Images** - Export to PNG, JPG, WebP, and more
- 📋 **Clipboard Support** - Copy images directly to system clipboard
- 🐳 **Docker Ready** - Run as a containerized service

## Quick Start

### Installation

```bash
# Using pip
pip install mcp-screenshot-server

# Using uv (recommended)
uv add mcp-screenshot-server

# From source
git clone https://github.com/aamar-shahzad/mcp-screenshot-server.git
cd mcp-screenshot-server
pip install -e .
```

### Running the Server

```bash
# stdio transport (default - for Cursor AI, Claude Desktop, etc.)
mcp-screenshot-server

# HTTP transport (for web clients)
mcp-screenshot-server --transport streamable-http --port 8000

# SSE transport
mcp-screenshot-server --transport sse --port 8000
```

## Integration with Cursor AI

### Method 1: Local Installation (Recommended)

1. **Install the package**:

   ```bash
   pip install mcp-screenshot-server
   # or
   uv tool install mcp-screenshot-server
   ```

2. **Add to Cursor settings** (`~/.cursor/mcp.json` or workspace `.cursor/mcp.json`):

   ```json
   {
     "mcpServers": {
       "screenshot": {
         "command": "mcp-screenshot-server",
         "args": []
       }
     }
   }
   ```

3. **Restart Cursor** to load the MCP server.

### Method 2: Using uvx (No Installation)

```json
{
  "mcpServers": {
    "screenshot": {
      "command": "uvx",
      "args": ["mcp-screenshot-server"]
    }
  }
}
```

### Method 3: Using Docker

1. **Build the Docker image**:

   ```bash
   docker build -t mcp-screenshot-server .
   ```

2. **Add to Cursor settings**:
   ```json
   {
     "mcpServers": {
       "screenshot": {
         "command": "docker",
         "args": ["run", "-i", "--rm", "mcp-screenshot-server"]
       }
     }
   }
   ```

### Method 4: HTTP Transport

1. **Start the server**:

   ```bash
   mcp-screenshot-server --transport streamable-http --port 8000
   ```

2. **Add to Cursor settings**:
   ```json
   {
     "mcpServers": {
       "screenshot": {
         "url": "http://localhost:8000/mcp"
       }
     }
   }
   ```

## Available Tools

### Screenshot Capture

| Tool                 | Description                                        |
| -------------------- | -------------------------------------------------- |
| `capture_screenshot` | Capture full screen, region, or window screenshots |
| `load_image`         | Load an existing image file for annotation         |

### Annotation Tools

| Tool            | Description                            |
| --------------- | -------------------------------------- |
| `add_box`       | Draw rectangles/boxes on images        |
| `add_line`      | Draw lines on images                   |
| `add_arrow`     | Draw arrows on images                  |
| `add_text`      | Add text annotations                   |
| `add_circle`    | Draw circles/ellipses                  |
| `add_highlight` | Add semi-transparent highlight regions |

### Image Management

| Tool              | Description                            |
| ----------------- | -------------------------------------- |
| `list_images`     | List all images in the current session |
| `get_image`       | Get a specific image by ID             |
| `duplicate_image` | Create a copy of an existing image     |
| `delete_image`    | Remove an image from the session       |

### Export Tools

| Tool                | Description                               |
| ------------------- | ----------------------------------------- |
| `save_image`        | Save image to disk (PNG, JPG, WebP, etc.) |
| `copy_to_clipboard` | Copy image to system clipboard            |
| `get_image_base64`  | Get image as base64-encoded string        |

## Usage Examples

### Basic Screenshot and Annotation

```python
# In Cursor AI, you can ask:
# "Take a screenshot and add a red box around the error message"

# The AI will use these tools:
# 1. capture_screenshot() -> returns image_id
# 2. add_box(image_id, x=100, y=200, width=300, height=50, color="red")
# 3. save_image(image_id, path="~/Desktop/annotated.png")
```

### Creating a Bug Report Screenshot

```
User: Take a screenshot of my screen and highlight the button at coordinates
      (500, 300) with a red circle, add an arrow pointing to it, and save it.

AI uses:
1. capture_screenshot(mode="fullscreen")
2. add_circle(image_id, x=500, y=300, radius=40, color="red", line_width=3)
3. add_arrow(image_id, x1=400, y1=200, x2=480, y2=280, color="red")
4. add_text(image_id, x=350, y=180, text="Click here!", color="red")
5. save_image(image_id, path="~/Desktop/bug-report.png")
```

### Annotating an Existing Image

```
User: Load the image at ~/Downloads/mockup.png and add numbered callouts

AI uses:
1. load_image(path="~/Downloads/mockup.png")
2. add_circle(image_id, x=100, y=100, radius=20, color="blue", fill="blue")
3. add_text(image_id, x=92, y=88, text="1", color="white")
4. add_circle(image_id, x=300, y=200, radius=20, color="blue", fill="blue")
5. add_text(image_id, x=292, y=188, text="2", color="white")
6. save_image(image_id, path="~/Downloads/mockup-annotated.png")
```

## Docker Usage

### Build and Run

```bash
# Build the image
docker build -t mcp-screenshot-server .

# Run with stdio transport
docker run -i --rm mcp-screenshot-server

# Run with HTTP transport
docker run -p 8000:8000 mcp-screenshot-server \
    --transport streamable-http --port 8000

# Run with volume for saving screenshots
docker run -p 8000:8000 -v $(pwd)/screenshots:/app/screenshots \
    mcp-screenshot-server --transport streamable-http
```

### Docker Compose

```bash
# Start HTTP server
docker-compose up -d mcp-screenshot-server

# Start stdio server
docker-compose --profile stdio up -d mcp-screenshot-server-stdio
```

## Configuration

### Environment Variables

| Variable   | Description             | Default   |
| ---------- | ----------------------- | --------- |
| `MCP_HOST` | Host for HTTP transport | `0.0.0.0` |
| `MCP_PORT` | Port for HTTP transport | `8000`    |

### Command Line Arguments

```
mcp-screenshot-server [OPTIONS]

Options:
  --transport {stdio,streamable-http,sse}
                        Transport to use (default: stdio)
  --host HOST           Host for HTTP transports (default: 0.0.0.0)
  --port PORT           Port for HTTP transports (default: 8000)
```

## Platform Support

| Platform | Screenshot                | Clipboard        | Notes                |
| -------- | ------------------------- | ---------------- | -------------------- |
| macOS    | ✅ Native `screencapture` | ✅ AppleScript   | Full support         |
| Windows  | ✅ PIL ImageGrab          | ✅ PowerShell    | Full support         |
| Linux    | ✅ PIL/scrot              | ✅ xclip/wl-copy | Requires X11/Wayland |
| Docker   | ✅ With Xvfb              | ⚠️ Limited       | Headless mode        |

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/aamar-shahzad/mcp-screenshot-server.git
cd mcp-screenshot-server

# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src/
```

### Project Structure

```
mcp-screenshot-server/
├── src/
│   └── mcp_screenshot_server/
│       ├── __init__.py
│       └── server.py          # Main MCP server implementation
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── LICENSE
```

## Troubleshooting

### macOS: "screencapture" requires screen recording permission

Go to **System Preferences > Privacy & Security > Screen Recording** and enable the terminal or IDE you're using.

### Linux: Clipboard not working

Install clipboard tools:

```bash
# For X11
sudo apt install xclip

# For Wayland
sudo apt install wl-clipboard
```

### Docker: Screenshots are blank

The Docker container runs in headless mode. For actual screen capture, you need to run the server natively on the host system.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- Image processing powered by [Pillow](https://pillow.readthedocs.io/)
