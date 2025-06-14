#!/usr/bin/env python3
"""
Script to remove training_type and coach references from test files
"""
import re

def fix_test_file():
    """Fix the trainings test file to remove training_type and coach references"""
    
    # Read the test file
    with open('trainings/tests.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove training_type from TrainingSession.objects.create calls
    content = re.sub(r',\s*training_type=[\'"][^\'"]*[\'"]', '', content)
    
    # Remove training_type from data dictionaries
    content = re.sub(r',\s*[\'"]training_type[\'"]\s*:\s*[\'"][^\'"]*[\'"]', '', content)
    
    # Remove coach references if any
    content = re.sub(r',\s*coach=[^\s,)]+', '', content)
    content = re.sub(r',\s*[\'"]coach[\'"]\s*:\s*[^\s,}]+', '', content)
    
    # Write back the file
    with open('trainings/tests.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Successfully updated trainings/tests.py")

if __name__ == '__main__':
    fix_test_file()
