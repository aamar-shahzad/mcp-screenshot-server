"""Pydantic models for MCP Screenshot Server tool results."""

from pydantic import BaseModel, Field


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


class DeleteResult(BaseModel):
    """Result of deleting an image."""
    message: str = Field(description="Status message")


class UndoCountResult(BaseModel):
    """Result of getting undo count."""
    image_id: str = Field(description="Image ID")
    undo_count: int = Field(description="Number of available undo operations")


class ClipboardResult(BaseModel):
    """Result of clipboard operation."""
    message: str = Field(description="Status message")


class Base64Result(BaseModel):
    """Result of base64 encoding."""
    image_id: str = Field(description="Image ID")
    data: str = Field(description="Base64-encoded image data with data URI prefix")
    message: str = Field(description="Status message")


class PreviewResult(BaseModel):
    """Result of opening image in preview."""
    message: str = Field(description="Status message")
    path: str = Field(description="Path to the image file")


class MemoryStatsResult(BaseModel):
    """Memory usage statistics for the image store."""
    image_count: int = Field(description="Number of images in store")
    max_images: int = Field(description="Maximum allowed images")
    memory_mb: float = Field(description="Current memory usage in MB")
    max_memory_mb: int = Field(description="Maximum allowed memory in MB")
    undo_levels: int = Field(description="Maximum undo history per image")


class ConfigureLimitsResult(BaseModel):
    """Result of configuring memory limits."""
    max_images: int = Field(description="New maximum image count")
    max_memory_mb: int = Field(description="New maximum memory in MB")
    undo_levels: int = Field(description="New undo history limit")
    evicted_count: int = Field(description="Number of images evicted after applying new limits")
    message: str = Field(description="Status message")


class StepAnnotationResult(BaseModel):
    """Result of adding a step annotation (callout + arrow + optional text)."""
    image_id: str = Field(description="Image ID that was annotated")
    step_number: int = Field(description="The step number used")
    callout_position: tuple[int, int] = Field(description="Position of the callout circle")
    target_position: tuple[int, int] = Field(description="Position the arrow points to")
    message: str = Field(description="Status message")


class ComparisonResult(BaseModel):
    """Result of comparing two images."""
    image_id: str = Field(description="ID of the diff image created")
    difference_percentage: float = Field(description="Percentage of pixels that differ")
    identical: bool = Field(description="True if images are identical")
    message: str = Field(description="Status message")


class SessionExportResult(BaseModel):
    """Result of exporting a session."""
    path: str = Field(description="Path to the exported session file")
    image_count: int = Field(description="Number of images exported")
    total_size_mb: float = Field(description="Total size of exported data in MB")
    message: str = Field(description="Status message")


class SessionImportResult(BaseModel):
    """Result of importing a session."""
    image_count: int = Field(description="Number of images imported")
    image_ids: list[str] = Field(description="List of imported image IDs")
    message: str = Field(description="Status message")
