"""
Diagnostic script to check Google Drive service account setup
Run with: python manage.py shell < documents/check_google_drive.py
"""

import os
import json
from django.conf import settings

def check_google_drive():
    print("=" * 60)
    print("Google Drive Service Account Diagnostic")
    print("=" * 60)
    
    # Check for service account file
    service_account_path = os.path.join(settings.BASE_DIR, 'google-service-account.json')
    
    print(f"\n1. Checking service account file at: {service_account_path}")
    
    if not os.path.exists(service_account_path):
        print("   ❌ File NOT found!")
        print("   Checking environment variable...")
        
        env_var = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if env_var:
            print("   ✓ Found GOOGLE_SERVICE_ACCOUNT_JSON environment variable")
        else:
            print("   ❌ GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
            print("\n   Please create google-service-account.json in your backend folder")
            return
    else:
        print("   ✓ File found!")
        
        # Read and validate the file
        try:
            with open(service_account_path, 'r') as f:
                creds = json.load(f)
            
            print(f"\n2. Service Account Details:")
            print(f"   Project ID: {creds.get('project_id', 'NOT FOUND')}")
            print(f"   Client Email: {creds.get('client_email', 'NOT FOUND')}")
            print(f"   Token URI: {creds.get('token_uri', 'NOT FOUND')}")
            
            # Check if it's actually a service account
            if creds.get('type') != 'service_account':
                print(f"\n   ⚠️ WARNING: type is '{creds.get('type')}', expected 'service_account'")
                print("   This might not be a service account key file!")
            else:
                print(f"   ✓ Type: service_account")
                
        except json.JSONDecodeError as e:
            print(f"   ❌ Invalid JSON file: {e}")
            return
        except Exception as e:
            print(f"   ❌ Error reading file: {e}")
            return
    
    # Try to initialize the service
    print(f"\n3. Testing Google Drive API connection...")
    try:
        from documents.google_drive_service import get_drive_service
        
        drive_service = get_drive_service()
        print("   ✓ Service initialized successfully")
        
        # Check quota
        print(f"\n4. Checking storage quota...")
        try:
            quota = drive_service.get_storage_quota()
            limit = int(quota.get('limit', 0))
            usage = int(quota.get('usage', 0))
            usage_drive = int(quota.get('usageInDrive', 0))
            usage_trash = int(quota.get('usageInDriveTrash', 0))
            
            print(f"   Storage Limit: {limit / (1024**3):.2f} GB")
            print(f"   Total Usage: {usage / (1024**3):.2f} GB")
            print(f"   Drive Usage: {usage_drive / (1024**3):.2f} GB")
            print(f"   Trash Usage: {usage_trash / (1024**3):.2f} GB")
            print(f"   Available: {(limit - usage) / (1024**3):.2f} GB")
            
            if usage >= limit:
                print("\n   ❌ STORAGE QUOTA EXCEEDED!")
            else:
                print("\n   ✓ Storage quota OK")
                
        except Exception as e:
            print(f"   ❌ Error checking quota: {e}")
        
        # List files
        print(f"\n5. Listing existing files...")
        try:
            files = drive_service.list_all_files()
            print(f"   Found {len(files)} files in Drive")
            
            if files:
                print("\n   Files:")
                for f in files[:10]:  # Show first 10
                    size = int(f.get('size', 0)) if f.get('size') else 0
                    print(f"   - {f['name']} ({size / 1024:.1f} KB)")
                if len(files) > 10:
                    print(f"   ... and {len(files) - 10} more")
        except Exception as e:
            print(f"   ❌ Error listing files: {e}")
        
        # Try a simple operation
        print(f"\n6. Testing file creation...")
        try:
            # Create a small test file
            test_content = b"Test file content"
            result = drive_service.drive_service.files().create(
                body={'name': 'test_diagnostic.txt'},
                media_body=None,
                fields='id, name'
            ).execute()
            
            print(f"   ✓ Test file created: {result.get('id')}")
            
            # Delete it
            drive_service.delete_file(result['id'])
            print(f"   ✓ Test file deleted")
            
        except Exception as e:
            error_str = str(e)
            print(f"   ❌ Error: {e}")
            
            if 'storageQuotaExceeded' in error_str:
                print("\n   The 'storageQuotaExceeded' error can occur if:")
                print("   1. The service account's Drive is full (unlikely for new account)")
                print("   2. Billing is not enabled on the Google Cloud project")
                print("   3. There are API quota limits on the project")
                print("\n   Try these fixes:")
                print("   - Go to Google Cloud Console > APIs & Services > Dashboard")
                print("   - Check if Google Drive API shows any errors or quota issues")
                print("   - Go to Billing and ensure a billing account is linked")
                print("   - Check IAM & Admin > Service Accounts and verify the account is active")
    
    except Exception as e:
        print(f"   ❌ Failed to initialize service: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    check_google_drive()
else:
    check_google_drive()
