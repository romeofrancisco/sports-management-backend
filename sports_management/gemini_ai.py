import google.generativeai as genai
from django.conf import settings
from django.core.cache import cache
import concurrent.futures
import hashlib
import json
import time
import logging
import threading

# Configure logging
logger = logging.getLogger(__name__)

# Configure the Gemini AI with your API key
genai.configure(api_key=settings.GOOGLE_AI_API_KEY)

# Initialize the model - use gemini-2.5-flash for stable, fast responses
model = genai.GenerativeModel('gemini-2.5-flash')

# Rate limiting configuration - only triggers on actual API rate limit errors
RATE_LIMIT_CACHE_KEY = "gemini_ai_rate_limit_tracker"
MAX_REQUESTS_PER_MINUTE = 60  # Gemini API free tier allows ~60 RPM
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_BACKOFF_BASE = 2  # Base for exponential backoff
MAX_RETRIES = 3

# Thread-safe rate limiter
_rate_limit_lock = threading.Lock()


def _is_rate_limited():
    """Check if we're currently rate limited"""
    with _rate_limit_lock:
        rate_data = cache.get(RATE_LIMIT_CACHE_KEY, {'requests': [], 'backoff_until': 0})
        current_time = time.time()
        
        # Check if we're in a backoff period
        if rate_data.get('backoff_until', 0) > current_time:
            return True, rate_data['backoff_until'] - current_time
        
        # Clean old requests outside the window
        rate_data['requests'] = [
            req_time for req_time in rate_data.get('requests', [])
            if current_time - req_time < RATE_LIMIT_WINDOW
        ]
        
        # Check if we've exceeded the rate limit
        if len(rate_data['requests']) >= MAX_REQUESTS_PER_MINUTE:
            return True, RATE_LIMIT_WINDOW - (current_time - min(rate_data['requests']))
        
        return False, 0


def _record_request():
    """Record a new request for rate limiting"""
    with _rate_limit_lock:
        rate_data = cache.get(RATE_LIMIT_CACHE_KEY, {'requests': [], 'backoff_until': 0})
        current_time = time.time()
        
        # Clean old requests
        rate_data['requests'] = [
            req_time for req_time in rate_data.get('requests', [])
            if current_time - req_time < RATE_LIMIT_WINDOW
        ]
        
        # Add new request
        rate_data['requests'].append(current_time)
        cache.set(RATE_LIMIT_CACHE_KEY, rate_data, RATE_LIMIT_WINDOW * 2)


def _set_backoff(retry_count):
    """Set a backoff period after rate limit error"""
    with _rate_limit_lock:
        rate_data = cache.get(RATE_LIMIT_CACHE_KEY, {'requests': [], 'backoff_until': 0})
        backoff_seconds = RATE_LIMIT_BACKOFF_BASE ** retry_count
        rate_data['backoff_until'] = time.time() + backoff_seconds
        cache.set(RATE_LIMIT_CACHE_KEY, rate_data, RATE_LIMIT_WINDOW * 2)
        return backoff_seconds


def reset_rate_limit():
    """Reset rate limit state - call this if you want to clear rate limit tracking"""
    cache.delete(RATE_LIMIT_CACHE_KEY)


def _is_rate_limit_error(exception):
    """Check if an exception is a rate limit error"""
    error_str = str(exception).lower()
    return any(indicator in error_str for indicator in [
        'rate limit', 'rate_limit', 'quota', '429', 'resource exhausted',
        'too many requests', 'resourceexhausted'
    ])


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


def generate_response(prompt, timeout=25, cache_timeout=300, use_cache=True, max_retries=MAX_RETRIES, **kwargs):
    """
    Generate AI response with timeout protection, caching, and rate limiting
    
    Args:
        prompt (str): The prompt to send to the AI
        timeout (int): API request timeout in seconds
        cache_timeout (int): Cache duration in seconds (default: 5 minutes)
        use_cache (bool): Whether to use caching (default: True)
        max_retries (int): Maximum number of retries for rate limit errors
        **kwargs: Additional arguments for the AI model
    
    Returns:
        str: AI-generated response
    """
    # Check cache first if enabled
    if use_cache:
        cache_key = _create_cache_key('response', prompt, **kwargs)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Returning cached AI response")
            return cached_result
    
    # Check if we're rate limited
    is_limited, wait_time = _is_rate_limited()
    if is_limited:
        logger.warning(f"Rate limited, need to wait {wait_time:.1f} seconds")
        return f"Error generating response: AI service is temporarily rate limited. Please try again in {int(wait_time + 1)} seconds."
    
    last_error = None
    for retry in range(max_retries):
        try:
            # Record this request attempt
            _record_request()
            
            result = _execute_with_timeout(_generate_content_internal, timeout, prompt, **kwargs)
            
            # Cache successful result
            if use_cache and result and not result.startswith("Error"):
                cache.set(cache_key, result, cache_timeout)
            
            return result
            
        except TimeoutError as e:
            return f"Error generating response: {str(e)} - Please try again or reduce AI complexity."
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                backoff_seconds = _set_backoff(retry + 1)
                logger.warning(f"Rate limit hit, attempt {retry + 1}/{max_retries}. Backing off for {backoff_seconds}s")
                
                if retry < max_retries - 1:
                    time.sleep(min(backoff_seconds, 5))  # Cap sleep at 5 seconds per retry
                    continue
                else:
                    return f"Error generating response: AI service rate limit exceeded. Please wait a moment and try again."
            else:
                logger.error(f"AI generation error: {str(e)}")
                return f"Error generating response: {str(e)}"
    
    return f"Error generating response: {str(last_error)}"


def generate_chat(messages, timeout=25, cache_timeout=300, use_cache=True, max_retries=MAX_RETRIES, **kwargs):
    """
    Generate AI chat response with timeout protection, caching, and rate limiting
    
    Args:
        messages (list): List of message dictionaries with 'role' and 'content'
        timeout (int): API request timeout in seconds
        cache_timeout (int): Cache duration in seconds (default: 5 minutes)
        use_cache (bool): Whether to use caching (default: True)
        max_retries (int): Maximum number of retries for rate limit errors
        **kwargs: Additional arguments for the AI model
    
    Returns:
        str: AI-generated chat response
    """
    # Check cache first if enabled
    if use_cache:
        cache_key = _create_cache_key('chat', messages, **kwargs)
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            logger.debug("Returning cached AI chat response")
            return cached_result
    
    # Check if we're rate limited
    is_limited, wait_time = _is_rate_limited()
    if is_limited:
        logger.warning(f"Rate limited, need to wait {wait_time:.1f} seconds")
        return f"Error generating chat response: AI service is temporarily rate limited. Please try again in {int(wait_time + 1)} seconds."
    
    last_error = None
    for retry in range(max_retries):
        try:
            # Record this request attempt
            _record_request()
            
            result = _execute_with_timeout(_generate_chat_internal, timeout, messages, **kwargs)
            
            # Cache successful result
            if use_cache and result and not result.startswith("Error"):
                cache.set(cache_key, result, cache_timeout)
            
            return result
            
        except TimeoutError as e:
            return f"Error generating chat response: {str(e)} - Please try again or reduce complexity."
        except Exception as e:
            last_error = e
            if _is_rate_limit_error(e):
                backoff_seconds = _set_backoff(retry + 1)
                logger.warning(f"Rate limit hit, attempt {retry + 1}/{max_retries}. Backing off for {backoff_seconds}s")
                
                if retry < max_retries - 1:
                    time.sleep(min(backoff_seconds, 5))  # Cap sleep at 5 seconds per retry
                    continue
                else:
                    return f"Error generating chat response: AI service rate limit exceeded. Please wait a moment and try again."
            else:
                logger.error(f"AI chat generation error: {str(e)}")
                return f"Error generating chat response: {str(e)}"
    
    return f"Error generating chat response: {str(last_error)}"
