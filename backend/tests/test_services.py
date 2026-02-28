import pytest
import json
from unittest.mock import patch, mock_open, MagicMock
from app.services import AIService

@pytest.fixture
def mock_openai_response():
    mock_response = MagicMock()
    mock_message = MagicMock()
    
    mock_data = {
        "merchant_name": "Test Supermarket",
        "date": "2024-05-10",
        "total_amount": 150.00,
        "currency": "PLN",
        "items": [
            {"name": "Bread", "price": 5.0, "quantity": 1, "category": "Food"},
            {"name": "Milk", "price": 3.5, "quantity": 2, "category": "Food"}
        ]
    }
    
    mock_message.content = json.dumps(mock_data)
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response.choices = [mock_choice]
    
    return mock_response

@patch("app.services.client.chat.completions.create")
@patch("builtins.open", new_callable=mock_open, read_data=b"fake_image_data")
def test_parse_receipt_success(mock_file, mock_openai_create, mock_openai_response):
    # Setup mock
    mock_openai_create.return_value = mock_openai_response
    
    # Execute
    result = AIService.parse_receipt("fake/path/image.jpg")
    
    # Assertions
    assert result is not None
    assert result["merchant_name"] == "Test Supermarket"
    assert result["total_amount"] == 150.00
    assert len(result["items"]) == 2
    
    # Verify OpenAI was called correctly
    mock_openai_create.assert_called_once()
    
    # Verify file was opened
    mock_file.assert_called_once_with("fake/path/image.jpg", "rb")

@patch("builtins.open")
def test_parse_receipt_file_error(mock_file):
    # Setup mock to raise error when opening file
    mock_file.side_effect = Exception("File not found")
    
    # Execute
    result = AIService.parse_receipt("missing/path.jpg")
    
    # Assertions
    assert result is None
