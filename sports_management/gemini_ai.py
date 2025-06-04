import google.generativeai as genai
from django.conf import settings
import concurrent.futures
import time

# Configure the Gemini AI with your API key
genai.configure(api_key=settings.GOOGLE_AI_API_KEY)

# Initialize the model with the latest version
model = genai.GenerativeModel('gemini-2.0-flash')

def _execute_with_timeout(func, timeout, *args, **kwargs):
    """Execute a function with a timeout using ThreadPoolExecutor"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"AI request timed out after {timeout} seconds")

def _generate_content_internal(prompt, **kwargs):
    """Internal function to generate content"""
    response = model.generate_content(prompt, **kwargs)
    return response.text

def _generate_chat_internal(messages, **kwargs):
    """Internal function to generate chat"""
    chat = model.start_chat()
    for message in messages:
        if message['role'] == 'user':
            response = chat.send_message(message['content'], **kwargs)
    return response.text

def generate_response(prompt, timeout=25, **kwargs):
    """Generate AI response with timeout protection"""
    try:
        return _execute_with_timeout(_generate_content_internal, timeout, prompt, **kwargs)
    except TimeoutError as e:
        return f"Error generating response: {str(e)} - Please try again or reduce AI complexity."
    except Exception as e:
        return f"Error generating response: {str(e)}"

def generate_chat(messages, timeout=25, **kwargs):
    """Generate AI chat response with timeout protection"""
    try:
        return _execute_with_timeout(_generate_chat_internal, timeout, messages, **kwargs)
    except TimeoutError as e:
        return f"Error generating chat response: {str(e)} - Please try again or reduce complexity."
    except Exception as e:
        return f"Error generating chat response: {str(e)}"
