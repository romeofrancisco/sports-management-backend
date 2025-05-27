#!/usr/bin/env python3
"""
Comprehensive Test Suite for Role-Based Permissions System
Testing both backend API permissions and frontend integration
"""

import os
import sys
import django
import requests
import json
from datetime import datetime, timedelta

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from trainings.models import MetricUnit, TrainingCategory, TrainingSession, PlayerTraining, TrainingMetric
from teams.models import Team, Player, Coach
from sports.models import Sport

User = get_user_model()

class RolePermissionsTestSuite:
    """Comprehensive test suite for role-based permissions"""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.test_data = {}
        self.tokens = {}
        
    def setup_test_data(self):
        """Create test users, teams, and data for testing"""
        print("🔧 Setting up test data...")
        
        # Create sport
        self.sport = Sport.objects.get_or_create(
            name="Basketball",
            defaults={'max_players_on_field': 5}
        )[0]
        
        # Create test users with different roles
        self.admin_user = User.objects.create_user(
            username='admin_test',
            email='admin@test.com',
            password='test123',
            first_name='Admin',
            last_name='User',
            is_admin=True
        )
        
        self.coach_user = User.objects.create_user(
            username='coach_test',
            email='coach@test.com',
            password='test123',
            first_name='Coach',
            last_name='User',
            is_coach=True
        )
        
        self.player_user = User.objects.create_user(
            username='player_test',
            email='player@test.com',
            password='test123',
            first_name='Player',
            last_name='User',
            is_player=True
        )
        
        # Create teams
        self.team1 = Team.objects.create(
            name="Test Team 1",
            sport=self.sport,
            coach=self.coach_user.coach_profile if hasattr(self.coach_user, 'coach_profile') else None
        )
        
        self.team2 = Team.objects.create(
            name="Test Team 2", 
            sport=self.sport
        )
        
        # Create coach profile and assign team
        if not hasattr(self.coach_user, 'coach_profile'):
            coach_profile = Coach.objects.create(user=self.coach_user)
            coach_profile.teams.add(self.team1)
        else:
            self.coach_user.coach_profile.teams.add(self.team1)
            
        # Create player profile and assign to team
        if not hasattr(self.player_user, 'player_profile'):
            Player.objects.create(
                user=self.player_user,
                team=self.team1
            )
        else:
            self.player_user.player_profile.team = self.team1
            self.player_user.player_profile.save()
            
        # Create training categories and metrics
        self.category = TrainingCategory.objects.get_or_create(
            name="Fitness",
            defaults={'description': 'Physical fitness metrics'}
        )[0]
        
        # Create metric units (will test role-based creation)
        self.admin_unit = MetricUnit.objects.create(
            name="Kilometers",
            code="km",
            description="Distance in kilometers",
            created_by=self.admin_user,
            is_default=True
        )
        
        # Store test data for reference
        self.test_data = {
            'admin_user': self.admin_user,
            'coach_user': self.coach_user,
            'player_user': self.player_user,
            'team1': self.team1,
            'team2': self.team2,
            'category': self.category,
            'admin_unit': self.admin_unit
        }
        
        print("✅ Test data setup complete")
        
    def get_auth_token(self, username, password):
        """Get JWT token for authentication"""
        response = requests.post(f"{self.base_url}/api/auth/login/", {
            'username': username,
            'password': password
        })
        
        if response.status_code == 200:
            data = response.json()
            return data.get('access')
        else:
            print(f"❌ Failed to get token for {username}: {response.text}")
            return None
            
    def setup_auth_tokens(self):
        """Setup authentication tokens for all test users"""
        print("🔑 Setting up authentication tokens...")
        
        self.tokens = {
            'admin': self.get_auth_token('admin_test', 'test123'),
            'coach': self.get_auth_token('coach_test', 'test123'),
            'player': self.get_auth_token('player_test', 'test123')
        }
        
        for role, token in self.tokens.items():
            if token:
                print(f"✅ {role.capitalize()} token obtained")
            else:
                print(f"❌ Failed to get {role} token")
                
    def make_authenticated_request(self, method, endpoint, role, data=None):
        """Make authenticated request with role-specific token"""
        token = self.tokens.get(role)
        if not token:
            return None
            
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        url = f"{self.base_url}/api{endpoint}"
        
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data)
        elif method.upper() == 'PUT':
            response = requests.put(url, headers=headers, json=data)
        elif method.upper() == 'PATCH':
            response = requests.patch(url, headers=headers, json=data)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers)
        else:
            return None
            
        return response
        
    def test_metric_units_permissions(self):
        """Test metric units role-based permissions"""
        print("\n📊 Testing Metric Units Permissions...")
        
        # Test GET access (all roles should have read access)
        for role in ['admin', 'coach', 'player']:
            response = self.make_authenticated_request('GET', '/trainings/metric-units/', role)
            if response and response.status_code == 200:
                print(f"✅ {role.capitalize()} can read metric units")
            else:
                print(f"❌ {role.capitalize()} cannot read metric units: {response.status_code if response else 'No response'}")
                
        # Test POST access (only admin and coach should have write access)
        test_unit_data = {
            'name': 'Test Seconds',
            'code': 'ts',
            'description': 'Test time unit'
        }
        
        # Admin should be able to create
        response = self.make_authenticated_request('POST', '/trainings/metric-units/', 'admin', test_unit_data)
        if response and response.status_code == 201:
            admin_unit_id = response.json().get('id')
            print("✅ Admin can create metric units")
            
            # Check if admin-created unit is marked as default
            if response.json().get('is_default', False):
                print("✅ Admin-created units are marked as system default")
            else:
                print("❌ Admin-created units should be marked as system default")
        else:
            print(f"❌ Admin cannot create metric units: {response.status_code if response else 'No response'}")
            admin_unit_id = None
            
        # Coach should be able to create
        coach_unit_data = {
            'name': 'Coach Test Minutes',
            'code': 'ctm',
            'description': 'Coach-created time unit'
        }
        
        response = self.make_authenticated_request('POST', '/trainings/metric-units/', 'coach', coach_unit_data)
        if response and response.status_code == 201:
            coach_unit_id = response.json().get('id')
            print("✅ Coach can create metric units")
            
            # Check if coach-created unit is NOT marked as default
            if not response.json().get('is_default', True):
                print("✅ Coach-created units are NOT marked as system default")
            else:
                print("❌ Coach-created units should NOT be marked as system default")
        else:
            print(f"❌ Coach cannot create metric units: {response.status_code if response else 'No response'}")
            coach_unit_id = None
            
        # Player should NOT be able to create
        response = self.make_authenticated_request('POST', '/trainings/metric-units/', 'player', test_unit_data)
        if response and response.status_code in [403, 401]:
            print("✅ Player correctly denied create access")
        else:
            print(f"❌ Player should be denied create access: {response.status_code if response else 'No response'}")
            
        # Test UPDATE permissions
        if admin_unit_id:
            # Admin should be able to update any unit
            update_data = {'description': 'Updated by admin'}
            response = self.make_authenticated_request('PATCH', f'/trainings/metric-units/{admin_unit_id}/', 'admin', update_data)
            if response and response.status_code == 200:
                print("✅ Admin can update any metric unit")
            else:
                print(f"❌ Admin cannot update metric units: {response.status_code if response else 'No response'}")
                
            # Coach should NOT be able to update admin's unit (system default)
            response = self.make_authenticated_request('PATCH', f'/trainings/metric-units/{admin_unit_id}/', 'coach', update_data)
            if response and response.status_code in [403, 400]:
                print("✅ Coach correctly denied update access to system default units")
            else:
                print(f"❌ Coach should be denied update access to system defaults: {response.status_code if response else 'No response'}")
                
        if coach_unit_id:
            # Coach should be able to update their own unit
            update_data = {'description': 'Updated by coach'}
            response = self.make_authenticated_request('PATCH', f'/trainings/metric-units/{coach_unit_id}/', 'coach', update_data)
            if response and response.status_code == 200:
                print("✅ Coach can update their own metric units")
            else:
                print(f"❌ Coach cannot update their own metric units: {response.status_code if response else 'No response'}")
                
        # Test DELETE permissions
        if coach_unit_id:
            # Coach should be able to delete their own unit
            response = self.make_authenticated_request('DELETE', f'/trainings/metric-units/{coach_unit_id}/', 'coach')
            if response and response.status_code == 204:
                print("✅ Coach can delete their own metric units")
            else:
                print(f"❌ Coach cannot delete their own metric units: {response.status_code if response else 'No response'}")
                
    def test_training_session_permissions(self):
        """Test training session role-based permissions"""
        print("\n🏃 Testing Training Session Permissions...")
        
        # Test GET access with role-based filtering
        for role in ['admin', 'coach', 'player']:
            response = self.make_authenticated_request('GET', '/trainings/training-sessions/', role)
            if response and response.status_code == 200:
                data = response.json()
                session_count = data.get('count', len(data.get('results', [])))
                print(f"✅ {role.capitalize()} can read training sessions (found {session_count})")
            else:
                print(f"❌ {role.capitalize()} cannot read training sessions: {response.status_code if response else 'No response'}")
                
        # Test POST access (admin and coach should have access)
        session_data = {
            'title': 'Test Training Session',
            'description': 'Test session for permissions',
            'date': datetime.now().date().isoformat(),
            'start_time': '10:00:00',
            'end_time': '12:00:00',
            'team': self.team1.id,
            'training_type': 'team',
            'category': self.category.id
        }
        
        # Admin should be able to create
        response = self.make_authenticated_request('POST', '/trainings/training-sessions/', 'admin', session_data)
        if response and response.status_code == 201:
            print("✅ Admin can create training sessions")
            admin_session_id = response.json().get('id')
        else:
            print(f"❌ Admin cannot create training sessions: {response.status_code if response else 'No response'}")
            if response:
                print(f"Response: {response.text}")
            admin_session_id = None
            
        # Coach should be able to create for their team
        response = self.make_authenticated_request('POST', '/trainings/training-sessions/', 'coach', session_data)
        if response and response.status_code == 201:
            print("✅ Coach can create training sessions for their team")
            coach_session_id = response.json().get('id')
        else:
            print(f"❌ Coach cannot create training sessions: {response.status_code if response else 'No response'}")
            if response:
                print(f"Response: {response.text}")
            coach_session_id = None
            
        # Coach should NOT be able to create for other teams
        session_data_other_team = session_data.copy()
        session_data_other_team['team'] = self.team2.id
        
        response = self.make_authenticated_request('POST', '/trainings/training-sessions/', 'coach', session_data_other_team)
        if response and response.status_code in [403, 400]:
            print("✅ Coach correctly denied creating sessions for other teams")
        else:
            print(f"❌ Coach should be denied creating sessions for other teams: {response.status_code if response else 'No response'}")
            
        # Player should NOT be able to create
        response = self.make_authenticated_request('POST', '/trainings/training-sessions/', 'player', session_data)
        if response and response.status_code in [403, 401]:
            print("✅ Player correctly denied create access")
        else:
            print(f"❌ Player should be denied create access: {response.status_code if response else 'No response'}")
            
    def test_attendance_analytics_permissions(self):
        """Test attendance analytics role-based permissions"""
        print("\n📈 Testing Attendance Analytics Permissions...")
        
        analytics_endpoints = [
            '/trainings/attendance-analytics/overview/',
            '/trainings/attendance-analytics/trends/',
            '/trainings/attendance-analytics/heatmap/',
            '/trainings/attendance-analytics/players/'
        ]
        
        for endpoint in analytics_endpoints:
            print(f"\nTesting {endpoint}")
            
            for role in ['admin', 'coach', 'player']:
                response = self.make_authenticated_request('GET', endpoint, role)
                if response and response.status_code == 200:
                    print(f"✅ {role.capitalize()} can access {endpoint}")
                else:
                    print(f"❌ {role.capitalize()} cannot access {endpoint}: {response.status_code if response else 'No response'}")
                    
        # Test player detail endpoint with role-based filtering
        if hasattr(self.player_user, 'player_profile'):
            player_id = self.player_user.player_profile.user_id
            
            # Player should be able to view their own data
            response = self.make_authenticated_request('GET', f'/trainings/attendance-analytics/player_detail/?player_id={player_id}', 'player')
            if response and response.status_code == 200:
                print("✅ Player can view their own attendance data")
            else:
                print(f"❌ Player cannot view their own attendance data: {response.status_code if response else 'No response'}")
                
            # Coach should be able to view their team's player data
            response = self.make_authenticated_request('GET', f'/trainings/attendance-analytics/player_detail/?player_id={player_id}', 'coach')
            if response and response.status_code == 200:
                print("✅ Coach can view their team's player attendance data")
            else:
                print(f"❌ Coach cannot view their team's player data: {response.status_code if response else 'No response'}")
                
            # Admin should be able to view any player data
            response = self.make_authenticated_request('GET', f'/trainings/attendance-analytics/player_detail/?player_id={player_id}', 'admin')
            if response and response.status_code == 200:
                print("✅ Admin can view any player attendance data")
            else:
                print(f"❌ Admin cannot view player attendance data: {response.status_code if response else 'No response'}")
                
    def test_player_progress_permissions(self):
        """Test player progress role-based permissions"""
        print("\n📊 Testing Player Progress Permissions...")
        
        # Test basic player progress access
        for role in ['admin', 'coach', 'player']:
            response = self.make_authenticated_request('GET', '/trainings/player-progress/', role)
            if response and response.status_code == 200:
                data = response.json()
                player_count = data.get('count', len(data.get('results', [])))
                print(f"✅ {role.capitalize()} can access player progress (found {player_count} players)")
            else:
                print(f"❌ {role.capitalize()} cannot access player progress: {response.status_code if response else 'No response'}")
                
        # Test multi-player progress endpoint
        if self.team1.slug:
            response = self.make_authenticated_request('GET', f'/trainings/player-progress/multi_player/?team={self.team1.slug}&metric_id=1', 'coach')
            if response and response.status_code == 200:
                print("✅ Coach can access multi-player progress for their team")
            else:
                print(f"❌ Coach cannot access multi-player progress: {response.status_code if response else 'No response'}")
                
    def test_frontend_permission_integration(self):
        """Test frontend permission hook integration"""
        print("\n🖥️ Testing Frontend Permission Integration...")
        
        # This would normally test the frontend, but since we're in backend context,
        # we'll verify the API responses include the necessary permission data
        
        # Test metric units response includes created_by information
        response = self.make_authenticated_request('GET', '/trainings/metric-units/', 'coach')
        if response and response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            
            for unit in results:
                if 'created_by' in unit and 'created_by_name' in unit:
                    print("✅ Metric units include creator information for frontend permission checks")
                    break
            else:
                print("❌ Metric units missing creator information")
                
    def run_all_tests(self):
        """Run all permission tests"""
        print("🚀 Starting Comprehensive Role-Based Permissions Test Suite")
        print("=" * 60)
        
        try:
            self.setup_test_data()
            self.setup_auth_tokens()
            
            # Check if server is running
            try:
                response = requests.get(f"{self.base_url}/api/health/", timeout=5)
                if response.status_code != 200:
                    print("⚠️ Warning: Server may not be running properly")
            except requests.exceptions.RequestException:
                print("❌ Error: Cannot connect to server. Make sure the Django server is running.")
                return
                
            # Run all tests
            self.test_metric_units_permissions()
            self.test_training_session_permissions()
            self.test_attendance_analytics_permissions()
            self.test_player_progress_permissions()
            self.test_frontend_permission_integration()
            
            print("\n" + "=" * 60)
            print("✅ Role-based permissions test suite completed!")
            
        except Exception as e:
            print(f"\n❌ Test suite failed with error: {str(e)}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Run the test suite
    test_suite = RolePermissionsTestSuite()
    test_suite.run_all_tests()
