"""MCP Screenshot Server - Main server implementation."""

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage
from PIL import ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from pydantic import BaseModel, Field

from .models import (
    AnnotationResult,
    Base64Result,
    ClipboardResult,
    ComparisonResult,
    ConfigureLimitsResult,
    DeleteResult,
    ImageInfo,
    ImageListResult,
    MemoryStatsResult,
    PreviewResult,
    SaveResult,
    ScreenshotResult,
    SessionExportResult,
    SessionImportResult,
    StepAnnotationResult,
    UndoCountResult,
)
from .storage import (
    _image_history,
    _image_metadata,
    _image_order,
    _image_store,
    evict_if_needed,
    get_callout_counter,
    get_font,
    get_limits,
    get_next_callout_number,
    get_total_memory_mb,
    image_to_base64,
    remove_image_internal,
    set_callout_counter,
    store_image,
)
from .storage import (
    configure_limits as storage_configure_limits,
)
from .storage import (
    get_image as storage_get_image,
)
from .storage import (
    reset_callout_counter as storage_reset_callout_counter,
)

# Initialize the MCP server
mcp = FastMCP(
    "Screenshot Server",
    json_response=True,
    instructions="""
    MCP Screenshot Server - A powerful tool for capturing and annotating screenshots.

    ## 🎯 RECOMMENDED: Smart Annotation Tools (Use These!)

    ### annotate - Unified smart annotation with flexible positioning
    Position formats: named ("top-left", "center", "bottom-right"),
                     percentage ("50%, 30%"), or pixels ("100, 200")
    Example: annotate(img, "box", "top-left", width=200, color="blue")
    Example: annotate(img, "text", "center", text="Important!")
    Example: annotate(img, "arrow", "20%,50%", end_position="80%,50%")

    ### batch_annotate - Apply multiple annotations in ONE call
    Pass JSON array: [{"type":"box","position":"top-left"},{"type":"text","position":"center","text":"Hi"}]

    ### label_regions - Quickly label multiple areas
    Pass JSON object: {"Header":"top-center", "Sidebar":"center-left", "Main":"center"}

    ## Capture Tools:
    - capture_screenshot: Capture full screen, window, or region
    - load_image: Load an existing image file

    ## Basic Annotation Tools (for precise pixel control):
    - add_box, add_line, add_arrow, add_text, add_circle, add_highlight
    - add_numbered_callout, add_border

    ## Editing Tools:
    - blur_region, crop_image, resize_image, rotate_image, flip_image
    - adjust_brightness, adjust_contrast, add_watermark
    - undo, get_undo_count

    ## Export Tools:
    - save_image, quick_save, copy_to_clipboard, open_in_preview

    ## Session Tools:
    - list_images, get_image, duplicate_image, delete_image
    """,
)


# Aliases for backward compatibility with internal function names
_store_image = store_image
_get_image = storage_get_image
_image_to_base64 = image_to_base64
_get_font = get_font


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
    window_id: Annotated[int | None, Field(description="Window ID for window capture (macOS). Use 'osascript' or 'GetWindowID' to find window IDs.")] = None,
) -> ScreenshotResult:
    """
    Capture a screenshot of the screen, a region, or a specific window.

    On macOS, this uses the native screencapture command.
    On other systems, it uses PIL's ImageGrab or pyautogui as fallback.

    For window capture on macOS, you need the numeric window ID (not the window name).
    You can find window IDs using: osascript -e 'tell app "System Events" to get id of windows of processes'
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
                if window_id is not None:
                    # Capture specific window by ID (screencapture -l requires integer window ID)
                    cmd.extend(["-l", str(window_id)])
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
                raise RuntimeError(f"Screenshot capture failed: {e}") from e

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
    line_width: Annotated[int, Field(gt=0, description="Width of the box outline")] = 3,
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
    line_width: Annotated[int, Field(gt=0, description="Width of the line")] = 3,
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
    line_width: Annotated[int, Field(gt=0, description="Width of the arrow line")] = 3,
    head_size: Annotated[int, Field(description="Size of the arrow head")] = 15,
) -> AnnotationResult:
    """Draw an arrow on the image."""
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
    font_size: Annotated[int, Field(gt=0, description="Size of the font")] = 24,
    background: Annotated[str | None, Field(description="Background color for the text")] = None,
) -> AnnotationResult:
    """Add text annotation to the image."""
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)

    font = _get_font(font_size)

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
    line_width: Annotated[int, Field(gt=0, description="Width of the circle outline")] = 3,
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
    opacity: Annotated[int, Field(ge=0, le=255, description="Opacity (0-255)")] = 100,
) -> AnnotationResult:
    """Add a semi-transparent highlight region to the image."""
    image = _get_image(image_id).convert("RGBA")

    # Create overlay
    overlay = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Parse color and add opacity
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
# Smart Annotation Tools (Unified & Auto-Positioning)
# =============================================================================

# Named position aliases - 5x5 grid for more precision
_NAMED_POSITIONS = {
    # 3x3 basic grid (edges at 5%)
    "top-left": (0.05, 0.05),
    "top-center": (0.5, 0.05),
    "top-right": (0.95, 0.05),
    "center-left": (0.05, 0.5),
    "center": (0.5, 0.5),
    "center-right": (0.95, 0.5),
    "bottom-left": (0.05, 0.95),
    "bottom-center": (0.5, 0.95),
    "bottom-right": (0.95, 0.95),
    # 5x5 extended grid for more precision
    "top-left-quarter": (0.25, 0.25),
    "top-right-quarter": (0.75, 0.25),
    "bottom-left-quarter": (0.25, 0.75),
    "bottom-right-quarter": (0.75, 0.75),
    # Edge midpoints
    "top-left-edge": (0.0, 0.0),
    "top-right-edge": (1.0, 0.0),
    "bottom-left-edge": (0.0, 1.0),
    "bottom-right-edge": (1.0, 1.0),
}

# Anchor points for element alignment
_ANCHORS = {
    "top-left": (0.0, 0.0),
    "top-center": (0.5, 0.0),
    "top-right": (1.0, 0.0),
    "center-left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "center-right": (1.0, 0.5),
    "bottom-left": (0.0, 1.0),
    "bottom-center": (0.5, 1.0),
    "bottom-right": (1.0, 1.0),
}


def _parse_position(
    pos: str | tuple[float, float] | None,
    image_width: int,
    image_height: int,
    element_width: int = 0,
    element_height: int = 0,
    anchor: str = "center",
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[int, int]:
    """
    Parse position from named position, percentage, or pixels with anchor support.

    Formats:
    - Named: "top-left", "center", "bottom-right", etc.
    - Percentage: "50%, 30%" or (0.5, 0.3)
    - Pixels: "100px, 200px" or just "100, 200" for absolute positioning

    Anchor determines which part of the element aligns to the position:
    - "top-left": element's top-left corner at position
    - "center": element's center at position (default)
    - "bottom-right": element's bottom-right corner at position
    """
    if pos is None:
        return (0, 0)

    # Parse the position to get ratios (0-1) or absolute pixels
    is_absolute = False
    if isinstance(pos, tuple):
        px, py = pos
        if px > 1 or py > 1:
            is_absolute = True
    elif pos in _NAMED_POSITIONS:
        px, py = _NAMED_POSITIONS[pos]
    else:
        # Parse string like "50%, 30%" or "100px, 200px" or "100, 200"
        parts = [p.strip() for p in pos.split(",")]
        if len(parts) != 2:
            raise ValueError(f"Invalid position format: {pos}")

        def parse_value(v: str, max_val: int) -> tuple[float, bool]:
            v = v.strip()
            if v.endswith("%"):
                return float(v[:-1]) / 100.0, False
            if v.endswith("px"):
                return float(v[:-2]), True
            val = float(v)
            # If > 1 without %, treat as pixels
            if val > 1:
                return val, True
            return val, False

        px, abs_x = parse_value(parts[0], image_width)
        py, abs_y = parse_value(parts[1], image_height)
        is_absolute = abs_x or abs_y

        # If one is absolute, convert both to pixels
        if is_absolute:
            if not abs_x:
                px = px * image_width
            if not abs_y:
                py = py * image_height

    # Convert ratios to pixels
    if is_absolute:
        x, y = int(px), int(py)
    else:
        x = int(px * image_width)
        y = int(py * image_height)

    # Apply anchor adjustment
    anchor_x, anchor_y = _ANCHORS.get(anchor, (0.5, 0.5))
    x = x - int(element_width * anchor_x)
    y = y - int(element_height * anchor_y)

    # Apply offset
    x += offset_x
    y += offset_y

    # Clamp to image bounds (keep at least part of element visible)
    x = max(-element_width + 10, min(x, image_width - 10))
    y = max(-element_height + 10, min(y, image_height - 10))

    return (x, y)


def _auto_adjust_position(
    x: int, y: int,
    width: int, height: int,
    image_width: int, image_height: int,
    padding: int = 10
) -> tuple[int, int]:
    """Auto-adjust position to keep annotation within bounds with padding."""
    # Ensure annotation stays within image bounds with padding
    x = max(padding, min(x, image_width - width - padding))
    y = max(padding, min(y, image_height - height - padding))
    return (x, y)


class AnnotationSpec(BaseModel):
    """Specification for a single annotation."""
    type: Literal["box", "circle", "arrow", "text", "highlight", "line", "callout"]
    position: str = Field(description="Position: 'top-left', 'center', '50%,30%', or '100,200'")
    text: str | None = Field(default=None, description="Text for text/callout annotations")
    width: int | None = Field(default=None, description="Width for box/highlight")
    height: int | None = Field(default=None, description="Height for box/highlight")
    radius: int | None = Field(default=None, description="Radius for circle")
    end_position: str | None = Field(default=None, description="End position for arrow/line")
    color: str = Field(default="red", description="Color")
    line_width: int = Field(default=3, description="Line width")
    font_size: int = Field(default=24, description="Font size for text")


@mcp.tool()
def precise_annotate(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    annotation_type: Annotated[
        Literal["box", "circle", "text", "arrow", "line"],
        Field(description="Type of annotation")
    ],
    x: Annotated[int, Field(description="X coordinate in pixels (from left edge)")],
    y: Annotated[int, Field(description="Y coordinate in pixels (from top edge)")],
    text: Annotated[str | None, Field(description="Text content (for text type)")] = None,
    width: Annotated[int, Field(description="Width in pixels (for box)")] = 100,
    height: Annotated[int, Field(description="Height in pixels (for box)")] = 50,
    radius: Annotated[int, Field(description="Radius in pixels (for circle)")] = 30,
    x2: Annotated[int | None, Field(description="End X coordinate (for arrow/line)")] = None,
    y2: Annotated[int | None, Field(description="End Y coordinate (for arrow/line)")] = None,
    color: Annotated[str, Field(description="Color (name or hex)")] = "red",
    line_width: Annotated[int, Field(gt=0, description="Line/border width")] = 3,
    font_size: Annotated[int, Field(gt=0, description="Font size for text")] = 24,
) -> AnnotationResult:
    """
    Pixel-perfect annotation tool. Places annotations at EXACT pixel coordinates.
    No anchor adjustments, no auto-positioning - pure pixel placement.

    Coordinates:
    - x, y: Top-left corner for box, center for circle, start for text
    - x2, y2: End point for arrows/lines

    Examples:
    - precise_annotate(img, "box", x=100, y=200, width=150, height=50)
    - precise_annotate(img, "text", x=100, y=180, text="Label")
    - precise_annotate(img, "arrow", x=50, y=100, x2=200, y2=100)
    - precise_annotate(img, "circle", x=300, y=300, radius=40)
    """
    image = _get_image(image_id)
    draw = ImageDraw.Draw(image, "RGBA")
    message = ""

    if annotation_type == "box":
        draw.rectangle([x, y, x + width, y + height], outline=color, width=line_width)
        message = f"Box at ({x}, {y}) size {width}x{height}"

    elif annotation_type == "circle":
        circle_bbox = [x - radius, y - radius, x + radius, y + radius]
        draw.ellipse(circle_bbox, outline=color, width=line_width)
        message = f"Circle at ({x}, {y}) radius {radius}"

    elif annotation_type == "text":
        if not text:
            raise ValueError("text parameter required for text type")
        font = _get_font(font_size)
        # Add background for readability
        text_bbox = draw.textbbox((x, y), text, font=font)
        padding = 4
        draw.rectangle(
            [text_bbox[0] - padding, text_bbox[1] - padding, text_bbox[2] + padding, text_bbox[3] + padding],
            fill="white"
        )
        draw.text((x, y), text, fill=color, font=font)
        message = f"Text '{text}' at ({x}, {y})"

    elif annotation_type == "arrow":
        if x2 is None or y2 is None:
            raise ValueError("x2 and y2 required for arrow type")
        draw.line([(x, y), (x2, y2)], fill=color, width=line_width)
        # Draw arrowhead
        angle = math.atan2(y2 - y, x2 - x)
        head_size = 15
        left_angle = angle + math.pi * 0.85
        right_angle = angle - math.pi * 0.85
        left_x = x2 + head_size * math.cos(left_angle)
        left_y = y2 + head_size * math.sin(left_angle)
        right_x = x2 + head_size * math.cos(right_angle)
        right_y = y2 + head_size * math.sin(right_angle)
        draw.polygon([(x2, y2), (left_x, left_y), (right_x, right_y)], fill=color)
        message = f"Arrow from ({x}, {y}) to ({x2}, {y2})"

    elif annotation_type == "line":
        if x2 is None or y2 is None:
            raise ValueError("x2 and y2 required for line type")
        draw.line([(x, y), (x2, y2)], fill=color, width=line_width)
        message = f"Line from ({x}, {y}) to ({x2}, {y2})"

    _store_image(image, image_id)
    return AnnotationResult(image_id=image_id, message=message)


@mcp.tool()
def annotate(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    annotation_type: Annotated[
        Literal["box", "circle", "arrow", "text", "highlight", "line", "callout"],
        Field(description="Type of annotation")
    ],
    position: Annotated[
        str,
        Field(description="Position: named, percentage ('50%,30%'), or pixels ('100px,200px' or '100,200')")
    ] = "center",
    text: Annotated[str | None, Field(description="Text content (for text/callout types)")] = None,
    width: Annotated[int | None, Field(description="Width in pixels")] = None,
    height: Annotated[int | None, Field(description="Height in pixels")] = None,
    radius: Annotated[int | None, Field(description="Radius for circles")] = None,
    end_position: Annotated[str | None, Field(description="End position for arrows/lines")] = None,
    color: Annotated[str, Field(description="Color")] = "red",
    line_width: Annotated[int, Field(gt=0, description="Line width")] = 3,
    font_size: Annotated[int, Field(gt=0, description="Font size for text")] = 24,
    anchor: Annotated[
        str,
        Field(description="Anchor point: which part of element aligns to position (top-left, center, bottom-right, etc.)")
    ] = "center",
    offset_x: Annotated[int, Field(description="Horizontal offset in pixels (positive=right)")] = 0,
    offset_y: Annotated[int, Field(description="Vertical offset in pixels (positive=down)")] = 0,
    auto_adjust: Annotated[bool, Field(description="Auto-adjust to stay within bounds")] = True,
) -> AnnotationResult:
    """
    Smart unified annotation tool with flexible positioning and anchor support.

    Position formats:
    - Named: "top-left", "center", "bottom-right", "top-left-quarter", etc.
    - Percentage: "50%, 30%" (from top-left corner)
    - Pixels: "100px, 200px" or "100, 200" (absolute x, y)

    Anchor controls which part of the annotation aligns to the position:
    - "top-left": annotation's top-left corner at position
    - "center": annotation's center at position (default)
    - "bottom-right": annotation's bottom-right corner at position

    Offset allows fine-tuning: offset_x=10 moves 10px right, offset_y=-5 moves 5px up.

    Examples:
    - annotate(img, "box", "50%,10%", width=200, height=50, anchor="top-center")
    - annotate(img, "text", "100px,50px", text="Label", anchor="top-left", offset_x=5)
    - annotate(img, "callout", "center", text="Note", offset_y=-20)
    """
    image = _get_image(image_id)
    img_w, img_h = image.size

    # Calculate default sizes based on image
    default_width = max(100, img_w // 5)
    default_height = max(60, img_h // 8)
    default_radius = max(30, min(img_w, img_h) // 10)

    # Use provided or default values
    w = width or default_width
    h = height or default_height
    r = radius or default_radius

    # Parse start position with anchor and offset support
    x, y = _parse_position(
        position, img_w, img_h, w, h,
        anchor=anchor, offset_x=offset_x, offset_y=offset_y
    )

    # Auto-adjust if enabled
    if auto_adjust:
        if annotation_type in ["box", "highlight"]:
            x, y = _auto_adjust_position(x, y, w, h, img_w, img_h)
        elif annotation_type == "circle":
            x, y = _auto_adjust_position(x - r, y - r, r * 2, r * 2, img_w, img_h)
            x, y = x + r, y + r  # Convert back to center

    draw = ImageDraw.Draw(image, "RGBA")
    message = ""

    if annotation_type == "box":
        draw.rectangle([x, y, x + w, y + h], outline=color, width=line_width)
        message = f"Box at ({x},{y}) size {w}x{h}"

    elif annotation_type == "circle":
        circle_bbox = [x - r, y - r, x + r, y + r]
        draw.ellipse(circle_bbox, outline=color, width=line_width)
        message = f"Circle at ({x},{y}) radius {r}"

    elif annotation_type == "text":
        if not text:
            text = "Label"
        # Get font
        font = _get_font(font_size)

        # Add background for readability
        text_bbox = draw.textbbox((x, y), text, font=font)
        text_w = int(text_bbox[2] - text_bbox[0])
        text_h = int(text_bbox[3] - text_bbox[1])

        if auto_adjust:
            x, y = _auto_adjust_position(x, y, text_w + 10, text_h + 6, img_w, img_h)

        # Draw background
        draw.rectangle([x - 3, y - 3, x + text_w + 6, y + text_h + 6], fill=(0, 0, 0, 180))
        draw.text((x, y), text, fill=color, font=font)
        message = f"Text '{text}' at ({x},{y})"

    elif annotation_type == "callout":
        # Use numbered callout
        callout_num = get_next_callout_number()
        num = str(callout_num)
        callout_r = max(15, font_size // 2 + 5)

        # Draw circle background
        draw.ellipse(
            [x - callout_r, y - callout_r, x + callout_r, y + callout_r],
            fill=color, outline="white", width=2
        )

        # Draw number
        font = _get_font(font_size)

        num_bbox = draw.textbbox((0, 0), num, font=font)
        tw, th = num_bbox[2] - num_bbox[0], num_bbox[3] - num_bbox[1]
        draw.text((x - tw // 2, y - th // 2 - 2), num, fill="white", font=font)

        # Add label if provided
        if text:
            draw.text((x + callout_r + 5, y - th // 2), text, fill=color, font=font)

        message = f"Callout #{callout_num} at ({x},{y})" + (f" '{text}'" if text else "")

    elif annotation_type in ["arrow", "line"]:
        if not end_position:
            # Default: draw toward center
            ex, ey = img_w // 2, img_h // 2
        else:
            ex, ey = _parse_position(end_position, img_w, img_h)

        draw.line([(x, y), (ex, ey)], fill=color, width=line_width)

        if annotation_type == "arrow":
            # Draw arrowhead
            angle = math.atan2(ey - y, ex - x)
            head_size = line_width * 5

            left_x = ex - head_size * math.cos(angle - math.pi / 6)
            left_y = ey - head_size * math.sin(angle - math.pi / 6)
            right_x = ex - head_size * math.cos(angle + math.pi / 6)
            right_y = ey - head_size * math.sin(angle + math.pi / 6)

            draw.polygon([(ex, ey), (left_x, left_y), (right_x, right_y)], fill=color)
            message = f"Arrow from ({x},{y}) to ({ex},{ey})"
        else:
            message = f"Line from ({x},{y}) to ({ex},{ey})"

    elif annotation_type == "highlight":
        try:
            rgb = ImageColor.getrgb(color)
            rgba = (*rgb, 100)
        except ValueError:
            rgba = (255, 255, 0, 100)

        overlay = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([x, y, x + w, y + h], fill=rgba)
        image = PILImage.alpha_composite(image.convert("RGBA"), overlay)
        image = image.convert("RGB")
        message = f"Highlight at ({x},{y}) size {w}x{h}"

    _store_image(image, image_id)

    return AnnotationResult(image_id=image_id, message=message)


@mcp.tool()
def batch_annotate(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    annotations: Annotated[
        str,
        Field(description="""JSON array of annotations. Each object has:
        - type: "box"|"circle"|"arrow"|"text"|"highlight"|"line"|"callout"
        - position: "top-left", "center", "50%,30%", or "100,200"
        - Optional: text, width, height, radius, end_position, color, line_width, font_size

        Example: [{"type":"box","position":"top-left","width":100,"height":50,"color":"blue"},{"type":"text","position":"center","text":"Hello"}]""")
    ],
) -> AnnotationResult:
    """
    Apply multiple annotations in a single call.

    Pass a JSON array of annotation specs. Each annotation follows the same
    format as the annotate() tool.

    Example:
    [
        {"type": "box", "position": "top-left", "width": 200, "height": 100, "color": "blue"},
        {"type": "text", "position": "top-left", "text": "Header Area"},
        {"type": "arrow", "position": "center-left", "end_position": "center-right", "color": "green"},
        {"type": "callout", "position": "bottom-right", "text": "Click here"}
    ]
    """
    try:
        specs = json.loads(annotations)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(specs, list):
        raise ValueError("annotations must be a JSON array")

    messages = []
    for i, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise ValueError(f"Annotation {i} must be an object")

        ann_type = spec.get("type")
        if not ann_type:
            raise ValueError(f"Annotation {i} missing 'type'")

        result = annotate(
            image_id=image_id,
            annotation_type=ann_type,
            position=spec.get("position", "center"),
            text=spec.get("text"),
            width=spec.get("width"),
            height=spec.get("height"),
            radius=spec.get("radius"),
            end_position=spec.get("end_position"),
            color=spec.get("color", "red"),
            line_width=spec.get("line_width", 3),
            font_size=spec.get("font_size", 24),
            anchor=spec.get("anchor", "center"),
            offset_x=spec.get("offset_x", 0),
            offset_y=spec.get("offset_y", 0),
            auto_adjust=spec.get("auto_adjust", True),
        )
        messages.append(result.message)

    return AnnotationResult(
        image_id=image_id,
        message=f"Applied {len(specs)} annotations: " + "; ".join(messages)
    )


@mcp.tool()
def label_regions(
    image_id: Annotated[str, Field(description="ID of the image to label")],
    regions: Annotated[
        str,
        Field(description="""JSON object mapping region names to positions.
        Example: {"Header": "top-center", "Sidebar": "center-left", "Main Content": "center", "Footer": "bottom-center"}""")
    ],
    style: Annotated[
        Literal["box", "callout", "text"],
        Field(description="Style of labels")
    ] = "callout",
    color: Annotated[str, Field(description="Color for all labels")] = "red",
) -> AnnotationResult:
    """
    Quickly label multiple regions of an image.

    Pass a JSON object mapping region names to positions.

    Example:
    {
        "Navigation": "top-left",
        "Search Bar": "top-center",
        "User Menu": "top-right",
        "Sidebar": "center-left",
        "Main Content": "center",
        "Footer": "bottom-center"
    }
    """
    try:
        region_map = json.loads(regions)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(region_map, dict):
        raise ValueError("regions must be a JSON object")

    # Reset callout counter for consistent numbering
    storage_reset_callout_counter()

    messages = []
    for name, position in region_map.items():
        # Apply annotation (result is used implicitly - modifies image in store)
        annotate(
            image_id=image_id,
            annotation_type=style,
            position=position,
            text=name,
            color=color,
        )
        messages.append(f"{name} at {position}")

    return AnnotationResult(
        image_id=image_id,
        message=f"Labeled {len(region_map)} regions: " + ", ".join(messages)
    )


# =============================================================================
# Composite Annotation Tools
# =============================================================================


@mcp.tool()
def annotate_step(
    image_id: Annotated[str, Field(description="ID of the image to annotate")],
    step_number: Annotated[int | None, Field(description="Step number (auto-increments if None)", ge=1)] = None,
    target_position: Annotated[
        str,
        Field(description="Position the arrow points to. Named ('center'), percentage ('50%, 30%'), or pixels ('830px, 195px')")
    ] = "center",
    callout_position: Annotated[
        str | None,
        Field(description="Position for the callout. If None, auto-placed near target. Named, percentage, or pixels.")
    ] = None,
    text: Annotated[str | None, Field(description="Optional text label to display near the callout")] = None,
    color: Annotated[str, Field(description="Color for callout and arrow")] = "red",
    callout_size: Annotated[int, Field(description="Size of the callout circle", ge=20, le=100)] = 40,
    arrow_width: Annotated[int, Field(description="Width of the arrow line", ge=1, le=20)] = 3,
) -> StepAnnotationResult:
    """
    Add a numbered step annotation with callout circle, arrow, and optional text.

    This is a composite tool that combines a numbered callout with an arrow pointing
    to a target location. Useful for creating step-by-step tutorials or highlighting
    UI elements.

    If callout_position is not specified, it's automatically placed offset from the target.
    """
    if step_number is None:
        step_number = get_next_callout_number()

    image = _get_image(image_id)
    draw = ImageDraw.Draw(image)
    img_width, img_height = image.size

    # Parse target position
    target_x, target_y = _parse_position(target_position, img_width, img_height)

    # Auto-calculate callout position if not specified
    if callout_position is None:
        # Place callout offset from target, preferring top-left quadrant
        offset = callout_size + 50
        callout_x = target_x - offset if target_x > img_width // 2 else target_x + offset
        callout_y = target_y - offset if target_y > img_height // 2 else target_y + offset
        # Clamp to image bounds
        callout_x = max(callout_size, min(img_width - callout_size, callout_x))
        callout_y = max(callout_size, min(img_height - callout_size, callout_y))
    else:
        callout_x, callout_y = _parse_position(callout_position, img_width, img_height)

    # Draw arrow from callout to target
    angle = math.atan2(target_y - callout_y, target_x - callout_x)
    arrow_start_x = int(callout_x + (callout_size // 2 + 5) * math.cos(angle))
    arrow_start_y = int(callout_y + (callout_size // 2 + 5) * math.sin(angle))

    # Draw arrow line
    draw.line([(arrow_start_x, arrow_start_y), (target_x, target_y)], fill=color, width=arrow_width)

    # Draw arrow head
    head_size = 12
    angle1 = angle + math.pi * 0.8
    angle2 = angle - math.pi * 0.8
    head_x1 = target_x + head_size * math.cos(angle1)
    head_y1 = target_y + head_size * math.sin(angle1)
    head_x2 = target_x + head_size * math.cos(angle2)
    head_y2 = target_y + head_size * math.sin(angle2)
    draw.polygon([(target_x, target_y), (head_x1, head_y1), (head_x2, head_y2)], fill=color)

    # Draw callout circle
    radius = callout_size // 2
    draw.ellipse(
        [callout_x - radius, callout_y - radius, callout_x + radius, callout_y + radius],
        fill=color,
        outline=color
    )

    # Draw step number
    font_size = int(callout_size * 0.6)
    font = _get_font(font_size)
    number_text = str(step_number)
    text_bbox = draw.textbbox((0, 0), number_text, font=font)
    text_w = int(text_bbox[2] - text_bbox[0])
    text_h = int(text_bbox[3] - text_bbox[1])
    draw.text(
        (callout_x - text_w // 2, callout_y - text_h // 2 - 2),
        number_text,
        fill="white",
        font=font
    )

    # Draw optional text label
    if text:
        label_font = _get_font(16)
        label_bbox = draw.textbbox((0, 0), text, font=label_font)
        label_w = int(label_bbox[2] - label_bbox[0])
        label_h = int(label_bbox[3] - label_bbox[1])

        # Position label below callout
        label_x = callout_x - label_w // 2
        label_y = callout_y + radius + 8

        # Draw background for readability
        padding = 4
        draw.rectangle(
            [label_x - padding, label_y - padding, label_x + label_w + padding, label_y + label_h + padding],
            fill="white",
            outline=color
        )
        draw.text((label_x, label_y), text, fill=color, font=label_font)

    _store_image(image, image_id)

    return StepAnnotationResult(
        image_id=image_id,
        step_number=step_number,
        callout_position=(callout_x, callout_y),
        target_position=(target_x, target_y),
        message=f"Step {step_number} annotation added pointing to ({target_x}, {target_y})"
        + (f" with label '{text}'" if text else "")
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
    blur_strength: Annotated[int, Field(ge=1, le=50, description="Blur strength (1-50, higher = more blur)")] = 20,
    pixelate: Annotated[bool, Field(description="Use pixelation instead of blur")] = False,
) -> AnnotationResult:
    """
    Blur or pixelate a region of the image to hide sensitive information.

    Use this for hiding passwords, email addresses, personal info, etc.
    """
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
    if number is None:
        number = get_next_callout_number()

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
    callout_font_size = int(size * 0.6)
    font = _get_font(callout_font_size)

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
def reset_callout_counter() -> DeleteResult:
    """Reset the auto-increment callout counter to 0."""
    storage_reset_callout_counter()
    return DeleteResult(message="Callout counter reset to 0")


@mcp.tool()
def add_border(
    image_id: Annotated[str, Field(description="ID of the image")],
    width: Annotated[int, Field(description="Border width in pixels")] = 10,
    color: Annotated[str, Field(description="Border color")] = "#000000",
) -> ScreenshotResult:
    """Add a border around the entire image."""
    image = _get_image(image_id)

    # Parse color
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
) -> UndoCountResult:
    """Get the number of available undo operations for an image."""
    count = len(_image_history.get(image_id, []))
    return UndoCountResult(image_id=image_id, undo_count=count)


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

    # Determine the save directory (same paths work on macOS, Windows, and Linux)
    home = Path.home()
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
    opacity: Annotated[int, Field(ge=0, le=255, description="Opacity (0-255)")] = 128,
    font_size: Annotated[int, Field(gt=0, description="Font size")] = 24,
    color: Annotated[str, Field(description="Text color")] = "#ffffff",
) -> AnnotationResult:
    """Add a text watermark to the image."""
    image = _get_image(image_id).convert("RGBA")

    # Create watermark layer
    watermark = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(watermark)

    # Get font
    font = _get_font(font_size)

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
    image = _get_image(image_id)
    enhancer = ImageEnhance.Contrast(image)
    adjusted = enhancer.enhance(factor)

    _store_image(adjusted, image_id)

    return AnnotationResult(
        image_id=image_id,
        message=f"Contrast adjusted by factor {factor}"
    )


# =============================================================================
# Image Comparison Tools
# =============================================================================


@mcp.tool()
def compare_images(
    image_id_1: Annotated[str, Field(description="ID of the first image")],
    image_id_2: Annotated[str, Field(description="ID of the second image")],
    highlight_differences: Annotated[bool, Field(description="Create a diff image highlighting differences")] = True,
    threshold: Annotated[int, Field(ge=0, le=255, description="Color difference threshold (0-255). Pixels differing by more than this are marked.")] = 10,
    diff_color: Annotated[str, Field(description="Color to highlight differences")] = "red",
) -> ComparisonResult:
    """
    Compare two images and optionally create a diff image highlighting differences.

    Returns the percentage of pixels that differ and creates a new image showing
    the differences if highlight_differences is True.

    Useful for comparing before/after screenshots, detecting UI changes, or
    validating visual regression tests.
    """
    img1 = _get_image(image_id_1)
    img2 = _get_image(image_id_2)

    # Ensure same size for comparison
    if img1.size != img2.size:
        raise ValueError(
            f"Images must be the same size. Image 1: {img1.size}, Image 2: {img2.size}. "
            "Use resize_image to match dimensions first."
        )

    # Convert to RGB for comparison
    img1_rgb = img1.convert("RGB")
    img2_rgb = img2.convert("RGB")

    width, height = img1.size
    total_pixels = width * height
    diff_pixels = 0

    # Create diff image if requested
    diff_img: PILImage.Image | None = None
    diff_draw: ImageDraw.ImageDraw | None = None
    diff_color_rgb: tuple[int, ...] | None = None
    if highlight_differences:
        diff_img = img1_rgb.copy()
        diff_draw = ImageDraw.Draw(diff_img)
        diff_color_rgb = ImageColor.getrgb(diff_color)

    # Compare pixels
    for y in range(height):
        for x in range(width):
            # For RGB images, getpixel returns (R, G, B) tuples
            # Use type: ignore since PIL's type hints are overly broad for converted RGB images
            p1: tuple[int, int, int] = img1_rgb.getpixel((x, y))  # type: ignore[assignment]
            p2: tuple[int, int, int] = img2_rgb.getpixel((x, y))  # type: ignore[assignment]
            # Calculate color difference
            color_diff = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1]) + abs(p1[2] - p2[2])
            if color_diff > threshold * 3:  # threshold per channel
                diff_pixels += 1
                if diff_draw is not None and diff_color_rgb is not None:
                    diff_draw.point((x, y), fill=diff_color_rgb)

    diff_percentage = round((diff_pixels / total_pixels) * 100, 2)
    identical = diff_pixels == 0

    if highlight_differences and diff_img is not None:
        diff_id = _store_image(diff_img)
        message = f"Comparison complete. {diff_percentage}% of pixels differ."
        if not identical:
            message += f" Diff image saved as '{diff_id}'."
    else:
        diff_id = image_id_1  # Return first image ID if no diff created
        message = f"Comparison complete. {diff_percentage}% of pixels differ."

    return ComparisonResult(
        image_id=diff_id,
        difference_percentage=diff_percentage,
        identical=identical,
        message=message,
    )


@mcp.tool()
def create_side_by_side(
    image_id_1: Annotated[str, Field(description="ID of the first (left) image")],
    image_id_2: Annotated[str, Field(description="ID of the second (right) image")],
    label_1: Annotated[str, Field(description="Label for the first image")] = "Before",
    label_2: Annotated[str, Field(description="Label for the second image")] = "After",
    gap: Annotated[int, Field(ge=0, le=100, description="Gap between images in pixels")] = 20,
    label_height: Annotated[int, Field(ge=0, le=100, description="Height of label area (0 to disable labels)")] = 40,
    background_color: Annotated[str, Field(description="Background color for gap and labels")] = "#f0f0f0",
) -> ScreenshotResult:
    """
    Create a side-by-side comparison image from two images.

    Useful for visual comparisons, before/after documentation, or A/B testing screenshots.
    Labels are added above each image if label_height > 0.
    """
    img1 = _get_image(image_id_1)
    img2 = _get_image(image_id_2)

    # Calculate dimensions
    max_height = max(img1.height, img2.height)
    total_width = img1.width + gap + img2.width
    total_height = max_height + label_height

    # Create combined image
    bg_color = ImageColor.getrgb(background_color)
    combined = PILImage.new("RGB", (total_width, total_height), bg_color)

    # Paste images (vertically centered if different heights)
    y1_offset = label_height + (max_height - img1.height) // 2
    y2_offset = label_height + (max_height - img2.height) // 2

    combined.paste(img1, (0, y1_offset))
    combined.paste(img2, (img1.width + gap, y2_offset))

    # Add labels if enabled
    if label_height > 0:
        draw = ImageDraw.Draw(combined)
        font = _get_font(min(24, label_height - 8))

        # Label 1
        bbox1 = draw.textbbox((0, 0), label_1, font=font)
        text_w1 = bbox1[2] - bbox1[0]
        text_x1 = (img1.width - text_w1) // 2
        text_y1 = (label_height - (bbox1[3] - bbox1[1])) // 2
        draw.text((text_x1, text_y1), label_1, fill="black", font=font)

        # Label 2
        bbox2 = draw.textbbox((0, 0), label_2, font=font)
        text_w2 = bbox2[2] - bbox2[0]
        text_x2 = img1.width + gap + (img2.width - text_w2) // 2
        text_y2 = (label_height - (bbox2[3] - bbox2[1])) // 2
        draw.text((text_x2, text_y2), label_2, fill="black", font=font)

    result_id = _store_image(combined)

    return ScreenshotResult(
        image_id=result_id,
        width=total_width,
        height=total_height,
        message=f"Side-by-side comparison created: '{label_1}' ({img1.width}x{img1.height}) | '{label_2}' ({img2.width}x{img2.height})",
    )


# =============================================================================
# Image Management Tools
# =============================================================================


@mcp.tool()
def list_images() -> ImageListResult:
    """List all images stored in the current session."""
    images = []
    for image_id, data in _image_store.items():
        width, height = _image_metadata.get(image_id, (0, 0))
        images.append(ImageInfo(
            image_id=image_id,
            width=width,
            height=height,
            size_bytes=len(data)
        ))

    return ImageListResult(images=images, count=len(images))


@mcp.tool()
def get_memory_stats() -> MemoryStatsResult:
    """Get current memory usage statistics for the image store."""
    max_images, max_memory_mb, undo_levels = get_limits()
    return MemoryStatsResult(
        image_count=len(_image_store),
        max_images=max_images,
        memory_mb=round(get_total_memory_mb(), 2),
        max_memory_mb=max_memory_mb,
        undo_levels=undo_levels,
    )


@mcp.tool()
def configure_limits(
    max_images: Annotated[int | None, Field(description="Maximum number of images to keep (default: 50)", ge=1)] = None,
    max_memory_mb: Annotated[int | None, Field(description="Maximum memory in MB (default: 500)", ge=10)] = None,
    undo_levels: Annotated[int | None, Field(description="Maximum undo history per image (default: 10)", ge=1, le=100)] = None,
) -> ConfigureLimitsResult:
    """Configure memory limits for the image store. Triggers eviction if new limits are lower."""
    new_max_images, new_max_memory_mb, new_undo_levels, evicted = storage_configure_limits(
        max_images, max_memory_mb, undo_levels
    )

    return ConfigureLimitsResult(
        max_images=new_max_images,
        max_memory_mb=new_max_memory_mb,
        undo_levels=new_undo_levels,
        evicted_count=len(evicted),
        message=f"Limits updated. Evicted {len(evicted)} images." if evicted else "Limits updated.",
    )


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
) -> DeleteResult:
    """Delete an image from the session."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")

    remove_image_internal(image_id)
    return DeleteResult(message=f"Image '{image_id}' deleted successfully")


# =============================================================================
# Session Persistence Tools
# =============================================================================


@mcp.tool()
def export_session(
    path: Annotated[str, Field(description="Path to save the session archive (will be a .zip file)")],
    include_history: Annotated[bool, Field(description="Include undo history for each image")] = False,
) -> SessionExportResult:
    """
    Export all images and metadata to a zip archive for later restoration.

    The archive contains:
    - All images as PNG files
    - A manifest.json with image IDs, dimensions, and order
    - Optionally, undo history for each image

    Use import_session to restore the session later.
    """
    if not _image_store:
        raise ValueError("No images to export. Capture or load some images first.")

    path = os.path.expanduser(path)
    if not path.endswith(".zip"):
        path = f"{path}.zip"

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    images_list: list[dict[str, object]] = []
    manifest: dict[str, object] = {
        "version": "1.0",
        "created_at": datetime.now().isoformat(),
        "image_count": len(_image_store),
        "images": images_list,
        "image_order": _image_order.copy(),
        "callout_counter": get_callout_counter(),
    }

    total_bytes = 0

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for image_id, data in _image_store.items():
            # Save image
            zf.writestr(f"images/{image_id}.png", data)
            total_bytes += len(data)

            # Add to manifest
            width, height = _image_metadata.get(image_id, (0, 0))
            image_info = {
                "id": image_id,
                "width": width,
                "height": height,
                "size_bytes": len(data),
            }

            # Include history if requested
            if include_history and image_id in _image_history:
                history = _image_history[image_id]
                for i, hist_data in enumerate(history):
                    zf.writestr(f"history/{image_id}/{i}.png", hist_data)
                    total_bytes += len(hist_data)
                image_info["history_count"] = len(history)

            images_list.append(image_info)

        # Write manifest
        manifest_json = json.dumps(manifest, indent=2)
        zf.writestr("manifest.json", manifest_json)
        total_bytes += len(manifest_json)

    total_mb = round(total_bytes / (1024 * 1024), 2)

    return SessionExportResult(
        path=os.path.abspath(path),
        image_count=len(_image_store),
        total_size_mb=total_mb,
        message=f"Exported {len(_image_store)} images to {os.path.abspath(path)} ({total_mb} MB)",
    )


@mcp.tool()
def import_session(
    path: Annotated[str, Field(description="Path to the session archive (.zip file)")],
    merge: Annotated[bool, Field(description="Merge with existing session (True) or replace (False)")] = True,
    restore_history: Annotated[bool, Field(description="Restore undo history if available")] = True,
) -> SessionImportResult:
    """
    Import a previously exported session from a zip archive.

    By default, merges with the existing session. Set merge=False to replace
    all current images with the imported ones.
    """
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise ValueError(f"Session file not found: {path}")

    if not merge:
        # Clear existing session
        _image_store.clear()
        _image_history.clear()
        _image_metadata.clear()
        _image_order.clear()

    imported_ids = []

    with zipfile.ZipFile(path, "r") as zf:
        # Read manifest
        try:
            manifest_data = zf.read("manifest.json")
            manifest = json.loads(manifest_data)
        except KeyError as e:
            raise ValueError("Invalid session archive: missing manifest.json") from e

        # Import images
        for image_info in manifest.get("images", []):
            image_id = image_info["id"]
            image_path = f"images/{image_id}.png"

            try:
                image_data = zf.read(image_path)
            except KeyError:
                continue  # Skip missing images

            # Store image
            _image_store[image_id] = image_data
            _image_metadata[image_id] = (image_info.get("width", 0), image_info.get("height", 0))
            if image_id not in _image_order:
                _image_order.append(image_id)
            imported_ids.append(image_id)

            # Restore history if available and requested
            if restore_history and image_info.get("history_count", 0) > 0:
                _image_history[image_id] = []
                for i in range(image_info["history_count"]):
                    hist_path = f"history/{image_id}/{i}.png"
                    try:
                        hist_data = zf.read(hist_path)
                        _image_history[image_id].append(hist_data)
                    except KeyError:
                        break  # Stop if history file missing

        # Restore callout counter if not merging
        if not merge and "callout_counter" in manifest:
            set_callout_counter(manifest["callout_counter"])

    # Trigger eviction if needed
    evict_if_needed()

    return SessionImportResult(
        image_count=len(imported_ids),
        image_ids=imported_ids,
        message=f"Imported {len(imported_ids)} images from {path}",
    )


# =============================================================================
# Save and Export Tools
# =============================================================================


@mcp.tool()
def save_image(
    image_id: Annotated[str, Field(description="ID of the image to save")],
    path: Annotated[str, Field(description="File path to save the image to")],
    image_format: Annotated[
        Literal["png", "jpg", "jpeg", "bmp", "gif", "webp"],
        Field(description="Image format")
    ] = "png",
    quality: Annotated[int, Field(ge=1, le=100, description="Quality for JPEG (1-100)")] = 95,
) -> SaveResult:
    """Save an image to disk."""
    image = _get_image(image_id)

    # Expand user path
    path = os.path.expanduser(path)

    # Ensure directory exists
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # Add extension if not present
    if not any(path.lower().endswith(f".{ext}") for ext in ["png", "jpg", "jpeg", "bmp", "gif", "webp"]):
        path = f"{path}.{image_format}"

    # Save with appropriate settings
    save_kwargs = {}
    pil_format = image_format.upper()

    # PIL uses 'JPEG' not 'JPG'
    if pil_format == "JPG":
        pil_format = "JPEG"

    if image_format.lower() in ["jpg", "jpeg"]:
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
) -> ClipboardResult:
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
            return ClipboardResult(message="Image copied to clipboard successfully")
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
            return ClipboardResult(message="Image copied to clipboard successfully")
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
                return ClipboardResult(message="Image copied to clipboard successfully (xclip)")
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
                return ClipboardResult(message="Image copied to clipboard successfully (wl-copy)")
            except FileNotFoundError as e:
                raise RuntimeError(
                    "No clipboard tool found. Install xclip (X11) or wl-copy (Wayland)."
                ) from e
        finally:
            os.unlink(tmp_path)


@mcp.tool()
def get_image_base64(
    image_id: Annotated[str, Field(description="ID of the image")]
) -> Base64Result:
    """Get an image as a base64-encoded string."""
    base64_data = _image_to_base64(image_id)
    return Base64Result(
        image_id=image_id,
        data=f"data:image/png;base64,{base64_data}",
        message="Image encoded as base64"
    )


@mcp.tool()
def open_in_preview(
    image_id: Annotated[str, Field(description="ID of the image to open")],
    save_path: Annotated[str | None, Field(description="Optional path to save before opening")] = None,
) -> PreviewResult:
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
        return PreviewResult(message="Image opened in Preview.app", path=file_path)
    elif sys.platform == "win32":
        # Windows - use default viewer
        os.startfile(file_path)
        return PreviewResult(message="Image opened in default viewer", path=file_path)
    else:
        # Linux - use xdg-open
        subprocess.run(["xdg-open", file_path], check=True)
        return PreviewResult(message="Image opened in default viewer", path=file_path)


@mcp.tool()
def open_file_in_preview(
    path: Annotated[str, Field(description="Path to the image file to open")]
) -> PreviewResult:
    """
    Open an image file directly in the native Preview app (macOS) or default viewer.

    This doesn't require loading the image into the session first.
    """
    path = os.path.expanduser(path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Preview", path], check=True)
        return PreviewResult(message=f"Opened {path} in Preview.app", path=path)
    elif sys.platform == "win32":
        os.startfile(path)
        return PreviewResult(message=f"Opened {path} in default viewer", path=path)
    else:
        subprocess.run(["xdg-open", path], check=True)
        return PreviewResult(message=f"Opened {path} in default viewer", path=path)


# =============================================================================
# Server Entry Point
# =============================================================================


def main():
    """Run the MCP Screenshot Server."""
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

