#!/usr/bin/env python
import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Setup Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from dashboard.ai_analysis import analyze_system_health, collect_system_data
from sports_management.gemini_ai import generate_response
import json

def test_gemini_connection():
    """Test basic Gemini AI connection"""
    print("Testing Gemini AI connection...")
    try:
        response = generate_response("Hello, please respond with 'AI is working correctly!'")
        print(f"✅ Gemini AI Response: {response}")
        return True
    except Exception as e:
        print(f"❌ Gemini AI Error: {str(e)}")
        return False

def test_system_data_collection():
    """Test system data collection"""
    print("\nTesting system data collection...")
    try:
        system_data = collect_system_data()
        print(f"✅ System data collected successfully:")
        for key, value in system_data.items():
            print(f"   {key}: {value}")
        return system_data
    except Exception as e:
        print(f"❌ System data collection error: {str(e)}")
        return None

def test_ai_analysis():
    """Test full AI analysis"""
    print("\nTesting AI analysis...")
    try:
        system_data = collect_system_data()
        if system_data:
            ai_insights = analyze_system_health(system_data)
            print(f"✅ AI analysis completed successfully:")
            if 'ai_analysis' in ai_insights:
                for key, value in ai_insights['ai_analysis'].items():
                    print(f"   {key}: {value}")
            return True
        else:
            print("❌ Cannot test AI analysis without system data")
            return False
    except Exception as e:
        print(f"❌ AI analysis error: {str(e)}")
        return False

if __name__ == "__main__":
    print("=== AI Functionality Test ===")
    
    # Test 1: Basic Gemini connection
    gemini_works = test_gemini_connection()
    
    # Test 2: System data collection
    system_data = test_system_data_collection()
    
    # Test 3: Full AI analysis
    if gemini_works and system_data:
        ai_works = test_ai_analysis()
        
        if ai_works:
            print("\n🎉 All tests passed! AI functionality is working correctly.")
        else:
            print("\n⚠️ AI analysis failed but basic connection works.")
    else:
        print("\n❌ Basic tests failed. Check configuration.")
