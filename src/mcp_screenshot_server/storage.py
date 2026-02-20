"""Image storage with LRU eviction and undo history."""

import base64
import io
import os
from datetime import datetime

from PIL import Image as PILImage
from PIL import ImageFont

# Configuration from environment
_MAX_IMAGES = int(os.environ.get("MCP_MAX_IMAGES", "50"))
_MAX_MEMORY_MB = int(os.environ.get("MCP_MAX_MEMORY_MB", "500"))
_UNDO_LEVELS = int(os.environ.get("MCP_UNDO_LEVELS", "10"))

# In-memory image storage for the session (using dict for insertion-order LRU)
_image_store: dict[str, bytes] = {}
_image_history: dict[str, list[bytes]] = {}  # Undo history per image
_image_metadata: dict[str, tuple[int, int]] = {}  # image_id -> (width, height)
_image_order: list[str] = []  # Track insertion order for LRU
_image_counter = 0
_callout_counter = 0  # For auto-numbered callouts

# Cross-platform font paths
_FONT_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",  # macOS
    "/System/Library/Fonts/SFNSText.ttf",  # macOS fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux bold
    "C:\\Windows\\Fonts\\arial.ttf",  # Windows
    "C:\\Windows\\Fonts\\arialbd.ttf",  # Windows bold
]


def get_total_memory_mb() -> float:
    """Calculate total memory used by image store in MB."""
    total_bytes = sum(len(data) for data in _image_store.values())
    total_bytes += sum(
        sum(len(state) for state in history)
        for history in _image_history.values()
    )
    return total_bytes / (1024 * 1024)


def evict_if_needed() -> list[str]:
    """Evict oldest images if limits exceeded. Returns list of evicted IDs."""
    evicted = []

    # Evict by count
    while len(_image_store) > _MAX_IMAGES and _image_order:
        oldest_id = _image_order[0]
        remove_image_internal(oldest_id)
        evicted.append(oldest_id)

    # Evict by memory
    while get_total_memory_mb() > _MAX_MEMORY_MB and _image_order:
        oldest_id = _image_order[0]
        remove_image_internal(oldest_id)
        evicted.append(oldest_id)

    return evicted


def remove_image_internal(image_id: str) -> None:
    """Internal helper to remove image from all stores."""
    if image_id in _image_store:
        del _image_store[image_id]
    if image_id in _image_history:
        del _image_history[image_id]
    if image_id in _image_metadata:
        del _image_metadata[image_id]
    if image_id in _image_order:
        _image_order.remove(image_id)


def touch_image(image_id: str) -> None:
    """Move image to end of LRU order (most recently used)."""
    if image_id in _image_order:
        _image_order.remove(image_id)
        _image_order.append(image_id)


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Get a font at the specified size, with cross-platform fallback."""
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def generate_image_id() -> str:
    """Generate a unique image ID."""
    global _image_counter
    _image_counter += 1
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"img_{timestamp}_{_image_counter}"


def store_image(image: PILImage.Image, image_id: str | None = None, save_history: bool = True) -> str:
    """Store an image and return its ID. Triggers LRU eviction if limits exceeded."""
    is_new = image_id is None
    if is_new:
        image_id = generate_image_id()
        save_history = False  # Don't save history for new images

    # At this point image_id is guaranteed to be str
    assert image_id is not None

    # Save to undo history before overwriting
    if save_history and image_id in _image_store:
        if image_id not in _image_history:
            _image_history[image_id] = []
        _image_history[image_id].append(_image_store[image_id])
        if len(_image_history[image_id]) > _UNDO_LEVELS:
            _image_history[image_id].pop(0)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _image_store[image_id] = buffer.getvalue()
    _image_metadata[image_id] = (image.width, image.height)

    # Update LRU order
    if is_new:
        _image_order.append(image_id)
    else:
        touch_image(image_id)

    # Evict old images if needed
    evict_if_needed()

    return image_id


def get_image(image_id: str) -> PILImage.Image:
    """Retrieve an image by ID. Updates LRU order."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found. Use list_images to see available images.")
    touch_image(image_id)
    return PILImage.open(io.BytesIO(_image_store[image_id]))


def image_to_base64(image_id: str) -> str:
    """Convert stored image to base64."""
    if image_id not in _image_store:
        raise ValueError(f"Image '{image_id}' not found.")
    return base64.b64encode(_image_store[image_id]).decode("utf-8")


def get_next_callout_number() -> int:
    """Get and increment the callout counter."""
    global _callout_counter
    _callout_counter += 1
    return _callout_counter


def reset_callout_counter() -> None:
    """Reset the callout counter to 0."""
    global _callout_counter
    _callout_counter = 0


def get_callout_counter() -> int:
    """Get current callout counter value."""
    return _callout_counter


def set_callout_counter(value: int) -> None:
    """Set the callout counter to a specific value."""
    global _callout_counter
    _callout_counter = value


def configure_limits(
    max_images: int | None = None,
    max_memory_mb: int | None = None,
    undo_levels: int | None = None,
) -> tuple[int, int, int, list[str]]:
    """Configure memory limits. Returns (max_images, max_memory_mb, undo_levels, evicted_ids)."""
    global _MAX_IMAGES, _MAX_MEMORY_MB, _UNDO_LEVELS

    if max_images is not None:
        _MAX_IMAGES = max_images
    if max_memory_mb is not None:
        _MAX_MEMORY_MB = max_memory_mb
    if undo_levels is not None:
        _UNDO_LEVELS = undo_levels
        # Trim existing undo histories
        for image_id in _image_history:
            while len(_image_history[image_id]) > _UNDO_LEVELS:
                _image_history[image_id].pop(0)

    evicted = evict_if_needed()
    return _MAX_IMAGES, _MAX_MEMORY_MB, _UNDO_LEVELS, evicted


def get_limits() -> tuple[int, int, int]:
    """Get current limits (max_images, max_memory_mb, undo_levels)."""
    return _MAX_IMAGES, _MAX_MEMORY_MB, _UNDO_LEVELS
