from django.test import TestCase
from django.conf import settings
from ..gemini_ai import generate_response, generate_chat

class GeminiAITest(TestCase):
    def setUp(self):
        # Verify that the API key is configured
        self.assertIsNotNone(settings.GOOGLE_AI_API_KEY, "Google AI API key is not configured")

    def test_generate_response(self):
        """Test basic text generation"""
        prompt = "What are 3 key benefits of regular exercise?"
        response = generate_response(prompt)
        
        # Check if we got a non-empty response
        self.assertIsInstance(response, str)
        self.assertTrue(len(response) > 0)
        self.assertNotIn("Error generating response", response)

    def test_generate_chat(self):
        """Test chat-based interaction"""
        messages = [
            {"role": "user", "content": "What's the best way to warm up before exercise?"}
        ]
        response = generate_chat(messages)
        
        # Check if we got a valid chat response
        self.assertIsInstance(response, str)
        self.assertTrue(len(response) > 0)
        self.assertNotIn("Error generating chat response", response)

    def test_error_handling(self):
        """Test error handling with invalid input"""
        # Test with empty prompt
        response = generate_response("")
        self.assertIn("Error generating response", response)

        # Test with invalid message format
        invalid_messages = [{"invalid": "format"}]
        response = generate_chat(invalid_messages)
        self.assertIn("Error generating chat response", response)
