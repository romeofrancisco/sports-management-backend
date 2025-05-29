#!/usr/bin/env python
import os
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from dashboard.ai_analysis import analyze_system_health, collect_system_data

def debug_ai_analysis():
    print("=== Debugging AI Analysis ===")
    
    # Get system data
    print("\n1. Collecting system data...")
    system_data = collect_system_data()
    print(f"System data keys: {list(system_data.keys())}")
    
    # Run AI analysis
    print("\n2. Running AI analysis...")
    result = analyze_system_health(system_data)
    
    print("\n3. AI Analysis Result Structure:")
    print(f"Result keys: {list(result.keys())}")
    
    if 'ai_analysis' in result:
        print(f"\nAI Analysis keys: {list(result['ai_analysis'].keys())}")
        
        print("\n4. Individual AI Analysis Sections:")
        for key, value in result['ai_analysis'].items():
            print(f"\n{key}:")
            print(f"  Type: {type(value)}")
            print(f"  Length: {len(str(value)) if value else 0}")
            print(f"  Content: {value[:100]}..." if value and len(str(value)) > 100 else f"  Content: {value}")
    
    print(f"\n5. Full Result:")
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    debug_ai_analysis()
