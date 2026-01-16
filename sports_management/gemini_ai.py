import google.generativeai as genai
from django.conf import settings
from django.core.cache import cache
import concurrent.futures
import hashlib
import json
import time

# Configure the Gemini AI with your API key
genai.configure(api_key=settings.GOOGLE_AI_API_KEY)

# Initialize the model with the latest version
model = genai.GenerativeModel('gemini-3-flash-preview')

def _create_cache_key(prefix, *args, **kwargs):
    """Create a unique cache key from function arguments"""
    cache_data = {
        'prefix': prefix,
        'args': str(args),
        'kwargs': str(sorted(kwargs.items()))
    }
    cache_string = json.dumps(cache_data, sort_keys=True)
    return f"gemini_ai_{hashlib.md5(cache_string.encode()).hexdigest()}"

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

def generate_response(prompt, timeout=25, cache_timeout=300, use_cache=True, **kwargs):
    """
    Generate AI response with timeout protection and caching
    
    Args:
        prompt (str): The prompt to send to the AI
        timeout (int): API request timeout in seconds
        cache_timeout (int): Cache duration in seconds (default: 5 minutes)
        use_cache (bool): Whether to use caching (default: True)
        **kwargs: Additional arguments for the AI model
    
    Returns:
        str: AI-generated response
    """
    # Check cache first if enabled
    if use_cache:
        cache_key = _create_cache_key('response', prompt, **kwargs)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
    
    try:
        result = _execute_with_timeout(_generate_content_internal, timeout, prompt, **kwargs)
        
        # Cache successful result
        if use_cache and result and not result.startswith("Error"):
            cache.set(cache_key, result, cache_timeout)
        
        return result
    except TimeoutError as e:
        return f"Error generating response: {str(e)} - Please try again or reduce AI complexity."
    except Exception as e:
        return f"Error generating response: {str(e)}"

def generate_chat(messages, timeout=25, cache_timeout=300, use_cache=True, **kwargs):
    """
    Generate AI chat response with timeout protection and caching
    
    Args:
        messages (list): List of message dictionaries with 'role' and 'content'
        timeout (int): API request timeout in seconds
        cache_timeout (int): Cache duration in seconds (default: 5 minutes)
        use_cache (bool): Whether to use caching (default: True)
        **kwargs: Additional arguments for the AI model
    
    Returns:
        str: AI-generated chat response
    """
    # Check cache first if enabled
    if use_cache:
        cache_key = _create_cache_key('chat', messages, **kwargs)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
    
    try:
        result = _execute_with_timeout(_generate_chat_internal, timeout, messages, **kwargs)
        
        # Cache successful result
        if use_cache and result and not result.startswith("Error"):
            cache.set(cache_key, result, cache_timeout)
        
        return result
    except TimeoutError as e:
        return f"Error generating chat response: {str(e)} - Please try again or reduce complexity."
    except Exception as e:
        return f"Error generating chat response: {str(e)}"
