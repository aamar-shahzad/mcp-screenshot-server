"""MCP Screenshot Server - Main server implementation."""

import base64
import io
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage, ImageDraw, ImageFont
from pydantic import BaseModel, Field

# Initialize the MCP server
mcp = FastMCP(
    "Screenshot Server",
    json_response=True,
    instructions="""
    MCP Screenshot Server - A powerful tool for capturing and annotating screenshots.
    
    ## Capture Tools:
    - capture_screenshot: Capture full screen, window, or region screenshots
    - load_image: Load an existing image file
    
    ## Annotation Tools:
    - add_box: Draw rectangles/boxes
    - add_line: Draw lines
    - add_arrow: Draw arrows
    - add_text: Add text labels
    - add_circle: Draw circles
    - add_highlight: Semi-transparent highlights
    - add_numbered_callout: Add numbered callouts (1, 2, 3...)
    - add_border: Add border around entire image
    
    ## Editing Tools:
    - blur_region: Blur/pixelate sensitive areas (passwords, emails)
    - crop_image: Crop to specific region
    - resize_image: Resize with scale or dimensions
    - undo: Undo last annotation
    
    ## Export Tools:
    - save_image: Save to specific path
    - quick_save: Save to Desktop/Downloads/Documents
    - copy_to_clipboard: Copy to clipboard
    - open_in_preview: Open in native Preview.app (macOS)
    
    ## Session Tools:
    - list_images: List all images in session
    - get_image: View/retrieve an image
    - duplicate_image: Create a copy
    - delete_image: Remove from session
    """,
)

# In-memory image storage for the session
_image_store: dict[str, bytes] = {}
_image_history: dict[str, list[bytes]] = {}  # Undo history per image
_image_counter = 0
_callout_counter = 0  # For auto-numbered callouts


def _generate_image_id() -> str:
    """Generate a unique image ID."""
    global _image_counter
    _image_counter += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"img_{timestamp}_{_image_counter}"


def _store_image(image: PILImage.Image, image_id: str | None = None, save_history: bool = True) -> str:
    """Store an image and return its ID."""
    if image_id is None:
        image_id = _generate_image_id()
        save_history = False  # Don't save history for new images
    
    # Save to undo history before overwriting
    if save_history and image_id in _image_store:
        if image_id not in _image_history:
            _image_history[image_id] = []
        # Keep last 10 states for undo
        _image_history[image_id].append(_image_store[image_id])
        if len(_image_history[image_id]) > 10:
            _image_history[image_id].pop(0)
    
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _image_store[image_id] = buffer.getvalue()
    return image_id


def _get_image(image_id: str) -> PILImage.Image:
    """Retrieve an image by ID."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found. Use list_images to see available images.")
    return PILImage.open(io.BytesIO(_image_store[image_id]))


def _image_to_base64(image_id: str) -> str:
    """Convert stored image to base64."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")
    return base64.b64encode(_image_store[image_id]).decode("utf-8")


class ScreenshotResult(BaseModel):
    """Result of a screenshot capture."""
    image_id: str = Field(description="Unique identifier for the captured image")
    width: int = Field(description="Image width in pixels")
    height: int = Field(description="Image height in pixels")
    message: str = Field(description="Status message")


class AnnotationResult(BaseModel):
    """Result of an annotation operation."""
    image_id: str = Field(description="Image ID that was annotated")
    message: str = Field(description="Status message")


class SaveResult(BaseModel):
    """Result of saving an image."""
    path: str = Field(description="Full path where the image was saved")
    message: str = Field(description="Status message")


class ImageInfo(BaseModel):
    """Information about a stored image."""
    image_id: str
    width: int
    height: int
    size_bytes: int


class ImageListResult(BaseModel):
    """List of available images."""
    images: list[ImageInfo]
    count: int


# =============================================================================
# Screenshot Capture Tools
# =============================================================================


@mcp.tool()
def capture_screenshot(
    mode: Annotated[
        Literal["fullscreen", "region", "window"],
        Field(description="Capture mode: fullscreen, region (interactive selection), or window")
    ] = "fullscreen",
    x: Annotated[int | None, Field(description="X coordinate for region capture")] = None,
    y: Annotated[int | None, Field(description="Y coordinate for region capture")] = None,
    width: Annotated[int | None, Field(description="Width for region capture")] = None,
    height: Annotated[int | None, Field(description="Height for region capture")] = None,
    window_name: Annotated[str | None, Field(description="Window name for window capture (macOS)")] = None,
) -> ScreenshotResult:
    """
    Capture a screenshot of the screen, a region, or a specific window.
    
    On macOS, this uses the native screencapture command.
    On other systems, it uses PIL's ImageGrab or pyautogui as fallback.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if sys.platform == "darwin":
            # macOS - use native screencapture
            cmd = ["screencapture"]
            
            if mode == "region" and all(v is not None for v in [x, y, width, height]):
                # Capture specific region
                cmd.extend(["-R", f"{x},{y},{width},{height}"])
            elif mode == "region":
                # Interactive region selection
                cmd.append("-i")
            elif mode == "window":
                if window_name:
                    # Try to capture specific window by name
                    cmd.extend(["-l", window_name])
                else:
                    # Interactive window selection
                    cmd.append("-w")
            # fullscreen is default behavior
            
            cmd.append(tmp_path)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise RuntimeError(f"screencapture failed: {result.stderr}")
                
        else:
            # Windows/Linux - use PIL or pyautogui
            try:
                from PIL import ImageGrab
                
                if mode == "region" and all(v is not None for v in [x, y, width, height]):
                    bbox = (x, y, x + width, y + height)
                    screenshot = ImageGrab.grab(bbox=bbox)
                else:
                    screenshot = ImageGrab.grab()
                    
                screenshot.save(tmp_path, "PNG")
            except Exception as e:
                raise RuntimeError(f"Screenshot capture failed: {e}")
        
        # Load and store the image
        image = PILImage.open(tmp_path)
        image_id = _store_image(image)
        
        return ScreenshotResult(
            image_id=image_id,
            width=image.width,
            height=image.height,
            message=f"Screenshot captured successfully ({mode} mode)"
        )
        
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@mcp.tool()
def load_image(
    path: Annotated[str, Field(description="Path to the image file to load")]
) -> ScreenshotResult:
    """Load an existing image file for annotation."""
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image file not found: {path}")
    
    image = PILImage.open(path)
    image_id = _store_image(image)
    
    return ScreenshotResult(
        image_id=image_id,
        width=image.width,
        height=image.height,
        message=f"Image loaded from {path}"
    )


# =============================================================================
# Annotation Tools
# =============================================================================


@mcp.tool()
def add_box(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate of the top-left corner")],
    y: Annotated[int, Field(description="Y coordinate of the top-left corner")],
    width: Annotated[int, Field(description="Width of the box")],
    height: Annotated[int, Field(description="Height of the box")],
    color: Annotated[str, Field(description="Color of the box (e.g., 'red', '#FF0000')")] = "red",
    line_width: Annotated[int, Field(description="Width of the box outline")] = 3,
    fill: Annotated[str | None, Field(description="Fill color (None for no fill)")] = None,
) -> AnnotationResult:
    """Draw a rectangle/box on the image."""
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image, "RGBA")
    
    # Convert fill color with transparency if needed
    fill_color = None
    if fill:
        if fill.startswith("#") and len(fill) == 7:
            # Add transparency to hex color
            fill_color = fill + "80"  # 50% opacity
        else:
            fill_color = fill
    
    draw.rectangle(
        [x, y, x + width, y + height],
        outline=color,
        width=line_width,
        fill=fill_color
    )
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Box added at ({x}, {y}) with size {width}x{height}"
    )


@mcp.tool()
def add_line(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x1: Annotated[int, Field(description="X coordinate of the start point")],
    y1: Annotated[int, Field(description="Y coordinate of the start point")],
    x2: Annotated[int, Field(description="X coordinate of the end point")],
    y2: Annotated[int, Field(description="Y coordinate of the end point")],
    color: Annotated[str, Field(description="Color of the line")] = "red",
    line_width: Annotated[int, Field(description="Width of the line")] = 3,
) -> AnnotationResult:
    """Draw a line on the image."""
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)
    
    draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Line drawn from ({x1}, {y1}) to ({x2}, {y2})"
    )


@mcp.tool()
def add_arrow(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x1: Annotated[int, Field(description="X coordinate of the arrow start")],
    y1: Annotated[int, Field(description="Y coordinate of the arrow start")],
    x2: Annotated[int, Field(description="X coordinate of the arrow end (tip)")],
    y2: Annotated[int, Field(description="Y coordinate of the arrow end (tip)")],
    color: Annotated[str, Field(description="Color of the arrow")] = "red",
    line_width: Annotated[int, Field(description="Width of the arrow line")] = 3,
    head_size: Annotated[int, Field(description="Size of the arrow head")] = 15,
) -> AnnotationResult:
    """Draw an arrow on the image."""
    import math
    
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)
    
    # Draw the main line
    draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)
    
    # Calculate arrow head
    angle = math.atan2(y2 - y1, x2 - x1)
    angle1 = angle + math.pi * 0.8
    angle2 = angle - math.pi * 0.8
    
    # Arrow head points
    head_x1 = x2 + head_size * math.cos(angle1)
    head_y1 = y2 + head_size * math.sin(angle1)
    head_x2 = x2 + head_size * math.cos(angle2)
    head_y2 = y2 + head_size * math.sin(angle2)
    
    # Draw arrow head as filled triangle
    draw.polygon(
        [(x2, y2), (head_x1, head_y1), (head_x2, head_y2)],
        fill=color
    )
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Arrow drawn from ({x1}, {y1}) to ({x2}, {y2})"
    )


@mcp.tool()
def add_text(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate for the text")],
    y: Annotated[int, Field(description="Y coordinate for the text")],
    text: Annotated[str, Field(description="The text to add")],
    color: Annotated[str, Field(description="Color of the text")] = "red",
    font_size: Annotated[int, Field(description="Size of the font")] = 24,
    background: Annotated[str | None, Field(description="Background color for the text")] = None,
) -> AnnotationResult:
    """Add text annotation to the image."""
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)
    
    # Try to get a font, fall back to default
    font = None
    try:
        # Try common system fonts
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
            "C:\\Windows\\Fonts\\arial.ttf",  # Windows
        ]
        for font_path in font_paths:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, font_size)
                break
    except Exception:
        pass
    
    if font is None:
        font = ImageFont.load_default()
    
    # Draw background if specified
    if background:
        bbox = draw.textbbox((x, y), text, font=font)
        padding = 5
        draw.rectangle(
            [bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding],
            fill=background
        )
    
    draw.text((x, y), text, fill=color, font=font)
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Text '{text}' added at ({x}, {y})"
    )


@mcp.tool()
def add_circle(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate of the center")],
    y: Annotated[int, Field(description="Y coordinate of the center")],
    radius: Annotated[int, Field(description="Radius of the circle")],
    color: Annotated[str, Field(description="Color of the circle")] = "red",
    line_width: Annotated[int, Field(description="Width of the circle outline")] = 3,
    fill: Annotated[str | None, Field(description="Fill color (None for no fill)")] = None,
) -> AnnotationResult:
    """Draw a circle on the image."""
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image, "RGBA")
    
    # Calculate bounding box
    bbox = [x - radius, y - radius, x + radius, y + radius]
    
    draw.ellipse(bbox, outline=color, width=line_width, fill=fill)
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Circle added at ({x}, {y}) with radius {radius}"
    )


@mcp.tool()
def add_highlight(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate of the top-left corner")],
    y: Annotated[int, Field(description="Y coordinate of the top-left corner")],
    width: Annotated[int, Field(description="Width of the highlight area")],
    height: Annotated[int, Field(description="Height of the highlight area")],
    color: Annotated[str, Field(description="Color of the highlight")] = "yellow",
    opacity: Annotated[int, Field(description="Opacity (0-255)")] = 100,
) -> AnnotationResult:
    """Add a semi-transparent highlight region to the image."""
    image = _get_image(image_id).convert("RGBA")
    
    # Create overlay
    overlay = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Parse color and add opacity
    from PIL import ImageColor
    try:
        rgb = ImageColor.getrgb(color)
        rgba = (*rgb, opacity)
    except ValueError:
        rgba = (255, 255, 0, opacity)  # Default to yellow
    
    draw.rectangle([x, y, x + width, y + height], fill=rgba)
    
    # Composite the images
    result = PILImage.alpha_composite(image, overlay)
    result = result.convert("RGB")
    
    _store_image(result, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Highlight added at ({x}, {y}) with size {width}x{height}"
    )


# =============================================================================
# Advanced Editing Tools
# =============================================================================


@mcp.tool()
def blur_region(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate of the top-left corner")],
    y: Annotated[int, Field(description="Y coordinate of the top-left corner")],
    width: Annotated[int, Field(description="Width of the region to blur")],
    height: Annotated[int, Field(description="Height of the region to blur")],
    blur_strength: Annotated[int, Field(description="Blur strength (1-50, higher = more blur)")] = 20,
    pixelate: Annotated[bool, Field(description="Use pixelation instead of blur")] = False,
) -> AnnotationResult:
    """
    Blur or pixelate a region of the image to hide sensitive information.
    
    Use this for hiding passwords, email addresses, personal info, etc.
    """
    from PIL import ImageFilter
    
    image = _get_image(image_id)
    
    # Crop the region
    region = image.crop((x, y, x + width, y + height))
    
    if pixelate:
        # Pixelation: shrink and enlarge
        pixel_size = max(1, blur_strength // 2)
        small = region.resize(
            (max(1, region.width // pixel_size), max(1, region.height // pixel_size)),
            PILImage.Resampling.NEAREST
        )
        region = small.resize(region.size, PILImage.Resampling.NEAREST)
    else:
        # Gaussian blur
        region = region.filter(ImageFilter.GaussianBlur(radius=blur_strength))
    
    # Paste back
    image.paste(region, (x, y))
    _store_image(image, image_id)
    
    effect = "pixelated" if pixelate else "blurred"
    return AnnotationResult(
        image_id=image_id,
        message=f"Region {effect} at ({x}, {y}) with size {width}x{height}"
    )


@mcp.tool()
def crop_image(
    image_id: Annotated[str, Field(description="ID of the image to crop")],
    x: Annotated[int, Field(description="X coordinate of the top-left corner")],
    y: Annotated[int, Field(description="Y coordinate of the top-left corner")],
    width: Annotated[int, Field(description="Width of the crop area")],
    height: Annotated[int, Field(description="Height of the crop area")],
) -> ScreenshotResult:
    """Crop the image to a specific region."""
    image = _get_image(image_id)
    
    # Validate bounds
    x = max(0, min(x, image.width))
    y = max(0, min(y, image.height))
    width = min(width, image.width - x)
    height = min(height, image.height - y)
    
    cropped = image.crop((x, y, x + width, y + height))
    _store_image(cropped, image_id)
    
    return ScreenshotResult(
        image_id=image_id,
        width=cropped.width,
        height=cropped.height,
        message=f"Image cropped to {width}x{height} starting at ({x}, {y})"
    )


@mcp.tool()
def resize_image(
    image_id: Annotated[str, Field(description="ID of the image to resize")],
    width: Annotated[int | None, Field(description="New width (or None to calculate from height)")] = None,
    height: Annotated[int | None, Field(description="New height (or None to calculate from width)")] = None,
    scale: Annotated[float | None, Field(description="Scale factor (e.g., 0.5 for half size)")] = None,
    maintain_aspect: Annotated[bool, Field(description="Maintain aspect ratio")] = True,
) -> ScreenshotResult:
    """Resize the image by dimensions or scale factor."""
    image = _get_image(image_id)
    
    if scale is not None:
        new_width = int(image.width * scale)
        new_height = int(image.height * scale)
    elif width is not None and height is not None and not maintain_aspect:
        new_width = width
        new_height = height
    elif width is not None:
        new_width = width
        new_height = int(image.height * (width / image.width)) if maintain_aspect else image.height
    elif height is not None:
        new_height = height
        new_width = int(image.width * (height / image.height)) if maintain_aspect else image.width
    else:
        raise ValueError("Must specify width, height, or scale")
    
    resized = image.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
    _store_image(resized, image_id)
    
    return ScreenshotResult(
        image_id=image_id,
        width=new_width,
        height=new_height,
        message=f"Image resized to {new_width}x{new_height}"
    )


@mcp.tool()
def add_numbered_callout(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    x: Annotated[int, Field(description="X coordinate for the callout center")],
    y: Annotated[int, Field(description="Y coordinate for the callout center")],
    number: Annotated[int | None, Field(description="Number to display (auto-increments if None)")] = None,
    color: Annotated[str, Field(description="Background color of the callout")] = "#ff3333",
    text_color: Annotated[str, Field(description="Color of the number text")] = "#ffffff",
    size: Annotated[int, Field(description="Size of the callout circle")] = 40,
) -> AnnotationResult:
    """
    Add a numbered callout (circled number) to the image.
    
    Numbers auto-increment if not specified, making it easy to add sequential callouts.
    """
    global _callout_counter
    
    if number is None:
        _callout_counter += 1
        number = _callout_counter
    
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)
    
    # Draw circle background
    radius = size // 2
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=color,
        outline=color
    )
    
    # Draw number
    font = None
    font_size = int(size * 0.6)
    try:
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
        for font_path in font_paths:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, font_size)
                break
    except Exception:
        pass
    
    if font is None:
        font = ImageFont.load_default()
    
    text = str(number)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    text_x = x - text_width // 2
    text_y = y - text_height // 2 - 2  # Slight adjustment for visual centering
    
    draw.text((text_x, text_y), text, fill=text_color, font=font)
    
    _store_image(image, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Callout #{number} added at ({x}, {y})"
    )


@mcp.tool()
def reset_callout_counter() -> dict[str, str]:
    """Reset the auto-increment callout counter to 0."""
    global _callout_counter
    _callout_counter = 0
    return {"message": "Callout counter reset to 0"}


@mcp.tool()
def add_border(
    image_id: Annotated[str, Field(description="ID of the image")],
    width: Annotated[int, Field(description="Border width in pixels")] = 10,
    color: Annotated[str, Field(description="Border color")] = "#000000",
) -> ScreenshotResult:
    """Add a border around the entire image."""
    from PIL import ImageOps
    
    image = _get_image(image_id)
    
    # Parse color
    from PIL import ImageColor
    try:
        border_color = ImageColor.getrgb(color)
    except ValueError:
        border_color = (0, 0, 0)
    
    bordered = ImageOps.expand(image, border=width, fill=border_color)
    _store_image(bordered, image_id)
    
    return ScreenshotResult(
        image_id=image_id,
        width=bordered.width,
        height=bordered.height,
        message=f"Added {width}px border"
    )


@mcp.tool()
def undo(
    image_id: Annotated[str, Field(description="ID of the image to undo")]
) -> AnnotationResult:
    """Undo the last annotation on an image."""
    if image_id not in _image_history or not _image_history[image_id]:
        raise ValueError(f"No undo history available for image '{image_id}'")
    
    # Restore previous state
    _image_store[image_id] = _image_history[image_id].pop()
    
    remaining = len(_image_history[image_id])
    return AnnotationResult(
        image_id=image_id,
        message=f"Undo successful. {remaining} more undo(s) available."
    )


@mcp.tool()
def get_undo_count(
    image_id: Annotated[str, Field(description="ID of the image")]
) -> dict[str, int]:
    """Get the number of available undo operations for an image."""
    count = len(_image_history.get(image_id, []))
    return {"image_id": image_id, "undo_count": count}


@mcp.tool()
def quick_save(
    image_id: Annotated[str, Field(description="ID of the image to save")],
    filename: Annotated[str, Field(description="Filename (without path)")] = "screenshot.png",
    location: Annotated[
        Literal["desktop", "downloads", "documents", "temp"],
        Field(description="Where to save the file")
    ] = "desktop",
) -> SaveResult:
    """
    Quick save to common locations (Desktop, Downloads, Documents, or temp).
    
    Automatically determines the correct path based on the operating system.
    """
    image = _get_image(image_id)
    
    # Determine the save directory
    home = Path.home()
    
    if sys.platform == "darwin":
        locations = {
            "desktop": home / "Desktop",
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "temp": Path(tempfile.gettempdir()),
        }
    elif sys.platform == "win32":
        locations = {
            "desktop": home / "Desktop",
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "temp": Path(tempfile.gettempdir()),
        }
    else:
        # Linux
        locations = {
            "desktop": home / "Desktop",
            "downloads": home / "Downloads",
            "documents": home / "Documents",
            "temp": Path(tempfile.gettempdir()),
        }
    
    save_dir = locations.get(location, locations["desktop"])
    save_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle filename conflicts
    save_path = save_dir / filename
    if save_path.exists():
        base = save_path.stem
        ext = save_path.suffix
        counter = 1
        while save_path.exists():
            save_path = save_dir / f"{base}_{counter}{ext}"
            counter += 1
    
    # Save the image
    image.save(save_path, "PNG")
    
    return SaveResult(
        path=str(save_path),
        message=f"Image saved to {save_path}"
    )


@mcp.tool()
def rotate_image(
    image_id: Annotated[str, Field(description="ID of the image to rotate")],
    angle: Annotated[
        Literal[90, 180, 270],
        Field(description="Rotation angle: 90 (left), 180, or 270 (right)")
    ] = 90,
) -> ScreenshotResult:
    """Rotate the image by 90, 180, or 270 degrees."""
    image = _get_image(image_id)
    
    # PIL rotates counter-clockwise, so we negate for intuitive behavior
    if angle == 90:
        rotated = image.transpose(PILImage.Transpose.ROTATE_90)
    elif angle == 180:
        rotated = image.transpose(PILImage.Transpose.ROTATE_180)
    else:  # 270
        rotated = image.transpose(PILImage.Transpose.ROTATE_270)
    
    _store_image(rotated, image_id)
    
    return ScreenshotResult(
        image_id=image_id,
        width=rotated.width,
        height=rotated.height,
        message=f"Image rotated {angle} degrees"
    )


@mcp.tool()
def flip_image(
    image_id: Annotated[str, Field(description="ID of the image to flip")],
    direction: Annotated[
        Literal["horizontal", "vertical"],
        Field(description="Flip direction: horizontal (mirror) or vertical")
    ] = "horizontal",
) -> ScreenshotResult:
    """Flip the image horizontally (mirror) or vertically."""
    image = _get_image(image_id)
    
    if direction == "horizontal":
        flipped = image.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
    else:
        flipped = image.transpose(PILImage.Transpose.FLIP_TOP_BOTTOM)
    
    _store_image(flipped, image_id)
    
    return ScreenshotResult(
        image_id=image_id,
        width=flipped.width,
        height=flipped.height,
        message=f"Image flipped {direction}ly"
    )


@mcp.tool()
def add_watermark(
    image_id: Annotated[str, Field(description="ID of the image")],
    text: Annotated[str, Field(description="Watermark text")],
    position: Annotated[
        Literal["bottom-right", "bottom-left", "top-right", "top-left", "center"],
        Field(description="Position of the watermark")
    ] = "bottom-right",
    opacity: Annotated[int, Field(description="Opacity (0-255)")] = 128,
    font_size: Annotated[int, Field(description="Font size")] = 24,
    color: Annotated[str, Field(description="Text color")] = "#ffffff",
) -> AnnotationResult:
    """Add a text watermark to the image."""
    from PIL import ImageColor
    
    image = _get_image(image_id).convert("RGBA")
    
    # Create watermark layer
    watermark = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(watermark)
    
    # Get font
    font = None
    try:
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
        for font_path in font_paths:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, font_size)
                break
    except Exception:
        pass
    
    if font is None:
        font = ImageFont.load_default()
    
    # Calculate text size
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Calculate position
    padding = 20
    if position == "bottom-right":
        x = image.width - text_width - padding
        y = image.height - text_height - padding
    elif position == "bottom-left":
        x = padding
        y = image.height - text_height - padding
    elif position == "top-right":
        x = image.width - text_width - padding
        y = padding
    elif position == "top-left":
        x = padding
        y = padding
    else:  # center
        x = (image.width - text_width) // 2
        y = (image.height - text_height) // 2
    
    # Parse color and add opacity
    try:
        rgb = ImageColor.getrgb(color)
        rgba = (*rgb, opacity)
    except ValueError:
        rgba = (255, 255, 255, opacity)
    
    draw.text((x, y), text, fill=rgba, font=font)
    
    # Composite
    result = PILImage.alpha_composite(image, watermark)
    result = result.convert("RGB")
    
    _store_image(result, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Watermark '{text}' added at {position}"
    )


@mcp.tool()
def adjust_brightness(
    image_id: Annotated[str, Field(description="ID of the image")],
    factor: Annotated[float, Field(description="Brightness factor (0.5=darker, 1.0=unchanged, 1.5=brighter)")] = 1.0,
) -> AnnotationResult:
    """Adjust image brightness."""
    from PIL import ImageEnhance
    
    image = _get_image(image_id)
    enhancer = ImageEnhance.Brightness(image)
    adjusted = enhancer.enhance(factor)
    
    _store_image(adjusted, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Brightness adjusted by factor {factor}"
    )


@mcp.tool()
def adjust_contrast(
    image_id: Annotated[str, Field(description="ID of the image")],
    factor: Annotated[float, Field(description="Contrast factor (0.5=less, 1.0=unchanged, 1.5=more)")] = 1.0,
) -> AnnotationResult:
    """Adjust image contrast."""
    from PIL import ImageEnhance
    
    image = _get_image(image_id)
    enhancer = ImageEnhance.Contrast(image)
    adjusted = enhancer.enhance(factor)
    
    _store_image(adjusted, image_id)
    
    return AnnotationResult(
        image_id=image_id,
        message=f"Contrast adjusted by factor {factor}"
    )


# =============================================================================
# Image Management Tools
# =============================================================================


@mcp.tool()
def list_images() -> ImageListResult:
    """List all images stored in the current session."""
    images = []
    for image_id, data in _image_store.items():
        img = PILImage.open(io.BytesIO(data))
        images.append(ImageInfo(
            image_id=image_id,
            width=img.width,
            height=img.height,
            size_bytes=len(data)
        ))
    
    return ImageListResult(images=images, count=len(images))


@mcp.tool()
def get_image(
    image_id: Annotated[str, Field(description="ID of the image to retrieve")]
) -> Image:
    """Get a specific image by its ID. Returns the image data."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found. Use list_images to see available images.")
    
    return Image(data=_image_store[image_id], format="png")


@mcp.tool()
def duplicate_image(
    image_id: Annotated[str, Field(description="ID of the image to duplicate")]
) -> ScreenshotResult:
    """Create a copy of an existing image."""
    image = _get_image(image_id)
    new_id = _store_image(image.copy())
    
    return ScreenshotResult(
        image_id=new_id,
        width=image.width,
        height=image.height,
        message=f"Image duplicated from {image_id} to {new_id}"
    )


@mcp.tool()
def delete_image(
    image_id: Annotated[str, Field(description="ID of the image to delete")]
) -> dict[str, str]:
    """Delete an image from the session."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")
    
    del _image_store[image_id]
    return {"message": f"Image '{image_id}' deleted successfully"}


# =============================================================================
# Save and Export Tools
# =============================================================================


@mcp.tool()
def save_image(
    image_id: Annotated[str, Field(description="ID of the image to save")],
    path: Annotated[str, Field(description="File path to save the image to")],
    format: Annotated[
        Literal["png", "jpg", "jpeg", "bmp", "gif", "webp"],
        Field(description="Image format")
    ] = "png",
    quality: Annotated[int, Field(description="Quality for JPEG (1-100)")] = 95,
) -> SaveResult:
    """Save an image to disk."""
    image = _get_image(image_id)
    
    # Expand user path
    path = os.path.expanduser(path)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    
    # Add extension if not present
    if not any(path.lower().endswith(f".{ext}") for ext in ["png", "jpg", "jpeg", "bmp", "gif", "webp"]):
        path = f"{path}.{format}"
    
    # Save with appropriate settings
    save_kwargs = {}
    pil_format = format.upper()
    
    # PIL uses 'JPEG' not 'JPG'
    if pil_format == "JPG":
        pil_format = "JPEG"
    
    if format.lower() in ["jpg", "jpeg"]:
        # Convert RGBA to RGB for JPEG
        if image.mode == "RGBA":
            image = image.convert("RGB")
        save_kwargs["quality"] = quality
    
    image.save(path, format=pil_format, **save_kwargs)
    
    return SaveResult(
        path=os.path.abspath(path),
        message=f"Image saved to {os.path.abspath(path)}"
    )


@mcp.tool()
def copy_to_clipboard(
    image_id: Annotated[str, Field(description="ID of the image to copy")]
) -> dict[str, str]:
    """Copy an image to the system clipboard."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")
    
    if sys.platform == "darwin":
        # macOS - use osascript with a temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(_image_store[image_id])
            tmp_path = tmp.name
        
        try:
            # Use AppleScript to copy image to clipboard
            script = f'''
            set theFile to POSIX file "{tmp_path}"
            set theImage to read theFile as TIFF picture
            set the clipboard to theImage
            '''
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            return {"message": "Image copied to clipboard successfully"}
        finally:
            os.unlink(tmp_path)
            
    elif sys.platform == "win32":
        # Windows - use PowerShell
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(_image_store[image_id])
            tmp_path = tmp.name
        
        try:
            ps_script = f'''
            Add-Type -AssemblyName System.Windows.Forms
            $image = [System.Drawing.Image]::FromFile("{tmp_path}")
            [System.Windows.Forms.Clipboard]::SetImage($image)
            '''
            subprocess.run(["powershell", "-Command", ps_script], check=True, capture_output=True)
            return {"message": "Image copied to clipboard successfully"}
        finally:
            os.unlink(tmp_path)
            
    else:
        # Linux - try xclip or wl-copy
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(_image_store[image_id])
            tmp_path = tmp.name
        
        try:
            # Try xclip first (X11)
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", tmp_path],
                    check=True,
                    capture_output=True
                )
                return {"message": "Image copied to clipboard successfully (xclip)"}
            except FileNotFoundError:
                pass
            
            # Try wl-copy (Wayland)
            try:
                with open(tmp_path, "rb") as f:
                    subprocess.run(
                        ["wl-copy", "-t", "image/png"],
                        stdin=f,
                        check=True,
                        capture_output=True
                    )
                return {"message": "Image copied to clipboard successfully (wl-copy)"}
            except FileNotFoundError:
                raise RuntimeError(
                    "No clipboard tool found. Install xclip (X11) or wl-copy (Wayland)."
                )
        finally:
            os.unlink(tmp_path)


@mcp.tool()
def get_image_base64(
    image_id: Annotated[str, Field(description="ID of the image")]
) -> dict[str, str]:
    """Get an image as a base64-encoded string."""
    base64_data = _image_to_base64(image_id)
    return {
        "image_id": image_id,
        "data": f"data:image/png;base64,{base64_data}",
        "message": "Image encoded as base64"
    }


@mcp.tool()
def open_in_preview(
    image_id: Annotated[str, Field(description="ID of the image to open")],
    save_path: Annotated[str | None, Field(description="Optional path to save before opening")] = None,
) -> dict[str, str]:
    """
    Open an image in the native Preview app (macOS only).
    
    On macOS, this opens the image in Preview.app for viewing and native annotation.
    On other platforms, it opens with the default image viewer.
    """
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")
    
    # Determine save path
    if save_path:
        file_path = os.path.expanduser(save_path)
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    else:
        # Create a temporary file that won't be auto-deleted
        file_path = os.path.join(
            tempfile.gettempdir(),
            f"mcp_screenshot_{image_id}.png"
        )
    
    # Save the image
    image = _get_image(image_id)
    image.save(file_path, "PNG")
    
    # Open with native application
    if sys.platform == "darwin":
        # macOS - use Preview.app
        subprocess.run(["open", "-a", "Preview", file_path], check=True)
        return {
            "message": f"Image opened in Preview.app",
            "path": file_path
        }
    elif sys.platform == "win32":
        # Windows - use default viewer
        os.startfile(file_path)
        return {
            "message": "Image opened in default viewer",
            "path": file_path
        }
    else:
        # Linux - use xdg-open
        subprocess.run(["xdg-open", file_path], check=True)
        return {
            "message": "Image opened in default viewer",
            "path": file_path
        }


@mcp.tool()
def open_file_in_preview(
    path: Annotated[str, Field(description="Path to the image file to open")]
) -> dict[str, str]:
    """
    Open an image file directly in the native Preview app (macOS) or default viewer.
    
    This doesn't require loading the image into the session first.
    """
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Preview", path], check=True)
        return {"message": f"Opened {path} in Preview.app"}
    elif sys.platform == "win32":
        os.startfile(path)
        return {"message": f"Opened {path} in default viewer"}
    else:
        subprocess.run(["xdg-open", path], check=True)
        return {"message": f"Opened {path} in default viewer"}


# =============================================================================
# Server Entry Point
# =============================================================================


def main():
    """Run the MCP Screenshot Server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Screenshot Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default="stdio",
        help="Transport to use (default: stdio)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP transports")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP transports")
    
    args = parser.parse_args()
    
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

