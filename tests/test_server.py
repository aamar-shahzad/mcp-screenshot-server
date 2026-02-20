"""Tests for MCP Screenshot Server tools."""

import io
import os
import tempfile
from pathlib import Path

import pytest
from PIL import Image as PILImage

# Import the server and storage modules
from mcp_screenshot_server import server, storage


class TestImageStorage:
    """Test image storage functions."""

    def test_generate_image_id(self):
        """Test that image IDs are unique."""
        id1 = storage.generate_image_id()
        id2 = storage.generate_image_id()
        assert id1 != id2
        assert id1.startswith("img_")

    def test_store_and_get_image(self):
        """Test storing and retrieving images."""
        # Create a test image
        img = PILImage.new("RGB", (100, 100), color="red")
        
        # Store it
        image_id = server._store_image(img)
        assert image_id in server._image_store
        
        # Retrieve it
        retrieved = server._get_image(image_id)
        assert retrieved.size == (100, 100)

    def test_get_nonexistent_image(self):
        """Test that getting a nonexistent image raises an error."""
        with pytest.raises(ValueError, match="not found"):
            server._get_image("nonexistent_id")


class TestAnnotationTools:
    """Test annotation tools."""

    @pytest.fixture
    def test_image(self):
        """Create a test image for annotations."""
        img = PILImage.new("RGB", (200, 200), color="white")
        image_id = server._store_image(img)
        yield image_id

    def test_add_box(self, test_image):
        """Test adding a box annotation."""
        result = server.add_box(
            image_id=test_image,
            x=10, y=10, width=50, height=50,
            color="red", line_width=2
        )
        assert result.image_id == test_image
        assert "Box added" in result.message

    def test_add_circle(self, test_image):
        """Test adding a circle annotation."""
        result = server.add_circle(
            image_id=test_image,
            x=100, y=100, radius=30,
            color="blue", line_width=3
        )
        assert result.image_id == test_image
        assert "Circle added" in result.message

    def test_add_arrow(self, test_image):
        """Test adding an arrow annotation."""
        result = server.add_arrow(
            image_id=test_image,
            x1=10, y1=10, x2=100, y2=100,
            color="green", line_width=2
        )
        assert result.image_id == test_image
        assert "Arrow drawn" in result.message

    def test_add_text(self, test_image):
        """Test adding text annotation."""
        result = server.add_text(
            image_id=test_image,
            x=50, y=50, text="Hello",
            color="black", font_size=20
        )
        assert result.image_id == test_image
        assert "Text 'Hello' added" in result.message

    def test_add_highlight(self, test_image):
        """Test adding a highlight region."""
        result = server.add_highlight(
            image_id=test_image,
            x=20, y=20, width=80, height=40,
            color="yellow", opacity=100
        )
        assert result.image_id == test_image
        assert "Highlight added" in result.message


class TestEditingTools:
    """Test editing tools."""

    @pytest.fixture
    def test_image(self):
        """Create a test image for editing."""
        img = PILImage.new("RGB", (200, 200), color="white")
        image_id = server._store_image(img)
        yield image_id

    def test_crop_image(self, test_image):
        """Test cropping an image."""
        result = server.crop_image(
            image_id=test_image,
            x=10, y=10, width=100, height=100
        )
        assert result.width == 100
        assert result.height == 100

    def test_resize_image_by_scale(self, test_image):
        """Test resizing an image by scale factor."""
        result = server.resize_image(
            image_id=test_image,
            scale=0.5
        )
        assert result.width == 100
        assert result.height == 100

    def test_resize_image_by_width(self, test_image):
        """Test resizing an image by width."""
        result = server.resize_image(
            image_id=test_image,
            width=100,
            maintain_aspect=True
        )
        assert result.width == 100
        assert result.height == 100

    def test_rotate_image(self, test_image):
        """Test rotating an image."""
        result = server.rotate_image(
            image_id=test_image,
            angle=90
        )
        # 200x200 image rotated 90 degrees is still 200x200
        assert result.width == 200
        assert result.height == 200

    def test_flip_image(self, test_image):
        """Test flipping an image."""
        result = server.flip_image(
            image_id=test_image,
            direction="horizontal"
        )
        assert result.width == 200
        assert result.height == 200


class TestUndoFeature:
    """Test undo functionality."""

    @pytest.fixture
    def test_image(self):
        """Create a test image."""
        img = PILImage.new("RGB", (200, 200), color="white")
        image_id = server._store_image(img, save_history=False)
        yield image_id

    def test_undo_after_annotation(self, test_image):
        """Test undo after adding annotation."""
        # Add a box (this should save history)
        server.add_box(
            image_id=test_image,
            x=10, y=10, width=50, height=50,
            color="red"
        )
        
        # Check undo count
        count = server.get_undo_count(test_image)
        assert count.undo_count >= 1
        
        # Undo
        result = server.undo(test_image)
        assert "Undo successful" in result.message

    def test_undo_no_history(self, test_image):
        """Test undo with no history raises error."""
        with pytest.raises(ValueError, match="No undo history"):
            server.undo(test_image)


class TestSaveTools:
    """Test save and export tools."""

    @pytest.fixture
    def test_image(self):
        """Create a test image."""
        img = PILImage.new("RGB", (100, 100), color="blue")
        image_id = server._store_image(img)
        yield image_id

    def test_save_image(self, test_image):
        """Test saving an image to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "test.png")
            result = server.save_image(
                image_id=test_image,
                path=save_path,
                image_format="png"
            )
            assert os.path.exists(result.path)
            assert "Image saved" in result.message

    def test_save_image_jpg(self, test_image):
        """Test saving as JPEG."""
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "test.jpg")
            result = server.save_image(
                image_id=test_image,
                path=save_path,
                image_format="jpg",
                quality=90
            )
            assert os.path.exists(result.path)


class TestImageManagement:
    """Test image management tools."""

    def test_list_images(self):
        """Test listing images."""
        # Create test images
        img1 = PILImage.new("RGB", (50, 50), color="red")
        img2 = PILImage.new("RGB", (100, 100), color="blue")
        id1 = server._store_image(img1)
        id2 = server._store_image(img2)
        
        result = server.list_images()
        assert result.count >= 2
        ids = [img.image_id for img in result.images]
        assert id1 in ids
        assert id2 in ids

    def test_duplicate_image(self):
        """Test duplicating an image."""
        img = PILImage.new("RGB", (100, 100), color="green")
        original_id = server._store_image(img)
        
        result = server.duplicate_image(original_id)
        assert result.image_id != original_id
        assert result.width == 100
        assert result.height == 100

    def test_delete_image(self):
        """Test deleting an image."""
        img = PILImage.new("RGB", (100, 100), color="yellow")
        image_id = server._store_image(img)
        
        result = server.delete_image(image_id)
        assert "deleted successfully" in result.message
        assert image_id not in server._image_store


class TestSmartAnnotation:
    """Test smart annotation tools."""

    @pytest.fixture
    def test_image(self):
        """Create a test image."""
        img = PILImage.new("RGB", (400, 300), color="white")
        image_id = server._store_image(img)
        yield image_id

    def test_annotate_box_named_position(self, test_image):
        """Test annotate with named position."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="box",
            position="top-left",
            width=100,
            height=50,
            color="blue"
        )
        assert "Box at" in result.message

    def test_annotate_box_percentage_position(self, test_image):
        """Test annotate with percentage position."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="box",
            position="50%, 50%",
            width=100,
            height=50,
            color="red"
        )
        assert "Box at" in result.message

    def test_annotate_text(self, test_image):
        """Test annotate text."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="text",
            position="center",
            text="Hello World",
            color="green"
        )
        assert "Text 'Hello World'" in result.message

    def test_annotate_circle(self, test_image):
        """Test annotate circle."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="circle",
            position="center",
            radius=50,
            color="purple"
        )
        assert "Circle at" in result.message

    def test_annotate_arrow(self, test_image):
        """Test annotate arrow."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="arrow",
            position="20%, 50%",
            end_position="80%, 50%",
            color="orange"
        )
        assert "Arrow from" in result.message

    def test_annotate_callout(self, test_image):
        """Test annotate callout."""
        result = server.annotate(
            image_id=test_image,
            annotation_type="callout",
            position="bottom-right",
            text="Important!",
            color="red"
        )
        assert "Callout #" in result.message

    def test_batch_annotate(self, test_image):
        """Test batch annotation."""
        annotations = '[{"type":"box","position":"top-left","width":50,"height":30},{"type":"text","position":"center","text":"Test"}]'
        result = server.batch_annotate(
            image_id=test_image,
            annotations=annotations
        )
        assert "Applied 2 annotations" in result.message

    def test_label_regions(self, test_image):
        """Test label regions."""
        regions = '{"Header": "top-center", "Sidebar": "center-left", "Main": "center"}'
        result = server.label_regions(
            image_id=test_image,
            regions=regions,
            style="callout",
            color="blue"
        )
        assert "Labeled 3 regions" in result.message


class TestPositionParsing:
    """Test position parsing helper."""

    def test_parse_named_position(self):
        """Test parsing named positions."""
        x, y = server._parse_position("center", 400, 300)
        assert 150 <= x <= 250  # Around center (with element adjustment)
        assert 100 <= y <= 200

    def test_parse_percentage_position(self):
        """Test parsing percentage positions."""
        x, y = server._parse_position("25%, 75%", 400, 300, 0, 0)
        assert x == 100  # 25% of 400
        assert y == 225  # 75% of 300

    def test_parse_pixel_position(self):
        """Test parsing pixel positions."""
        x, y = server._parse_position("150, 200", 400, 300, 0, 0)
        # Values > 1 are treated as pixels, converted to ratio then back
        assert x > 0
        assert y > 0

    def test_auto_adjust_keeps_in_bounds(self):
        """Test auto-adjust keeps annotations in bounds."""
        # Try to place at edge
        x, y = server._auto_adjust_position(395, 295, 50, 30, 400, 300)
        assert x + 50 <= 400  # Width stays in bounds
        assert y + 30 <= 300  # Height stays in bounds

