"""
Caching utilities for expensive operations
"""
from django.core.cache import cache
from functools import wraps
import hashlib
import json


def cache_ai_response(timeout=300):
    """
    Decorator to cache AI responses to reduce API calls and improve performance.
    
    Args:
        timeout (int): Cache timeout in seconds (default: 300 = 5 minutes)
    
    Usage:
        @cache_ai_response(timeout=600)
        def my_ai_function(prompt, context):
            return generate_response(prompt)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key_data = {
                'function': func.__name__,
                'args': str(args),
                'kwargs': str(sorted(kwargs.items()))
            }
            cache_key_string = json.dumps(cache_key_data, sort_keys=True)
            cache_key = f"ai_cache_{hashlib.md5(cache_key_string.encode()).hexdigest()}"
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        
        return wrapper
    return decorator


def cache_query_result(key_prefix, timeout=300):
    """
    Decorator to cache database query results.
    
    Args:
        key_prefix (str): Prefix for cache key
        timeout (int): Cache timeout in seconds
    
    Usage:
        @cache_query_result('team_stats', timeout=600)
        def get_team_statistics(team_id):
            return Team.objects.get(id=team_id).calculate_stats()
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key
            cache_key_data = {
                'prefix': key_prefix,
                'args': str(args),
                'kwargs': str(sorted(kwargs.items()))
            }
            cache_key_string = json.dumps(cache_key_data, sort_keys=True)
            cache_key = f"{key_prefix}_{hashlib.md5(cache_key_string.encode()).hexdigest()}"
            
            # Try to get from cache
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        
        return wrapper
    return decorator


def invalidate_cache_pattern(pattern):
    """
    Invalidate all cache keys matching a pattern.
    Note: This works with Redis backend. For other backends, keys need to be tracked separately.
    
    Args:
        pattern (str): Pattern to match cache keys (e.g., 'team_stats_*')
    """
    try:
        # This requires Redis backend
        from django.core.cache import caches
        cache_backend = caches['default']
        
        if hasattr(cache_backend, '_cache'):
            # Redis backend
            keys = cache_backend._cache.keys(pattern)
            if keys:
                cache_backend._cache.delete(*keys)
                return len(keys)
    except Exception:
        # Fallback: cache.clear() clears all cache (use with caution)
        pass
    
    return 0
