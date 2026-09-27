import base64
from io import BytesIO

import pytest
from PIL import Image

from kairos.application.image_input import ImageValidationError, validate_image


def png_data(size=(12, 8)):
    image = Image.new("RGB", size, "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


def test_valid_image_is_normalized_to_data_url_without_metadata():
    result = validate_image("image/png", png_data())
    assert result.mime_type == "image/png"
    assert result.data_url.startswith("data:image/png;base64,")
    assert (result.width, result.height) == (12, 8)
    assert len(result.sha256) == 64


def test_image_mime_must_match_actual_format():
    with pytest.raises(ImageValidationError, match="mismatched"):
        validate_image("image/jpeg", png_data())


def test_invalid_base64_and_corrupt_image_are_rejected():
    with pytest.raises(ImageValidationError, match="base64"):
        validate_image("image/png", "not base64!")
    with pytest.raises(ImageValidationError, match="decoded"):
        validate_image("image/png", base64.b64encode(b"not an image").decode())
