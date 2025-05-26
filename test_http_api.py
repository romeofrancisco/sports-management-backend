#!/usr/bin/env python
import requests
import json

def test_api_endpoint():
    """Test the actual HTTP API endpoint"""
    base_url = "http://127.0.0.1:8000/api"
    
    # Test with the player training ID we know exists
    player_training_id = 2451
    metrics_to_assign = [3, 2, 4, 5]  # Add one more metric
    
    url = f"{base_url}/trainings/player-trainings/{player_training_id}/assign_metrics/"
    payload = {"metrics": metrics_to_assign}
    
    print(f"Testing API endpoint: {url}")
    print(f"Payload: {payload}")
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            print("✅ API endpoint is working correctly!")
        else:
            print("❌ API endpoint failed")
            
    except Exception as e:
        print(f"❌ Error testing API: {e}")

if __name__ == "__main__":
    test_api_endpoint()
