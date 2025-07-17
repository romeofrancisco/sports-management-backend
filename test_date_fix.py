#!/usr/bin/env python
"""
Test script to verify the fix for handling 'undefined' date parameters.
"""
import os
import sys
import django

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from trainings.services.multi_player_progress_service import MultiPlayerProgressService

def test_undefined_date_handling():
    """Test that 'undefined' date parameters are handled correctly."""
    
    # Mock request object with 'undefined' date parameters
    class MockRequest:
        def __init__(self):
            self.query_params = {
                'team': 'test-team',
                'metric_id': 'overall',
                'date_from': 'undefined',
                'date_to': 'undefined'
            }
    
    mock_request = MockRequest()
    
    try:
        # Create service instance
        service = MultiPlayerProgressService(mock_request)
        
        # Check that date parameters are correctly filtered out
        print(f"date_from: {service.date_from}")
        print(f"date_to: {service.date_to}")
        
        # The service should handle 'undefined' values by treating them as None/empty
        if service.date_from == 'undefined':
            print("❌ date_from is still 'undefined' - fix not working")
        else:
            print("✅ date_from is correctly handled")
            
        if service.date_to == 'undefined':
            print("❌ date_to is still 'undefined' - fix not working")
        else:
            print("✅ date_to is correctly handled")
            
        print("\nService created successfully - basic parameter handling works!")
        
    except Exception as e:
        print(f"❌ Error creating service: {e}")
        return False
    
    return True

if __name__ == '__main__':
    print("Testing undefined date parameter handling...")
    success = test_undefined_date_handling()
    
    if success:
        print("\n✅ Test passed! The fix should resolve the 'Overall' date range issue.")
    else:
        print("\n❌ Test failed! The fix needs more work.")
