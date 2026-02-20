"""Pytest configuration and fixtures for MCP Screenshot Server tests."""

import pytest

from mcp_screenshot_server import storage


@pytest.fixture(autouse=True)
def isolate_global_state():
    """
    Save and restore global state around each test.
    
    This ensures tests don't leak state to each other and don't require
    manual cleanup in teardown.
    """
    # Save original state
    original_image_store = storage._image_store.copy()
    original_image_history = {k: v.copy() for k, v in storage._image_history.items()}
    original_image_metadata = storage._image_metadata.copy()
    original_image_order = storage._image_order.copy()
    original_image_counter = storage._image_counter
    original_callout_counter = storage._callout_counter

    yield

    # Restore original state
    storage._image_store.clear()
    storage._image_store.update(original_image_store)
    
    storage._image_history.clear()
    storage._image_history.update(original_image_history)
    
    storage._image_metadata.clear()
    storage._image_metadata.update(original_image_metadata)
    
    storage._image_order.clear()
    storage._image_order.extend(original_image_order)
    
    storage._image_counter = original_image_counter
    storage._callout_counter = original_callout_counter
