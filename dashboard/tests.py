from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from django.urls import reverse
from teams.models import Team, Player, Coach
from sports.models import Sport
from games.models import Game
from trainings.models import TrainingSession, PlayerTraining

User = get_user_model()


class DashboardViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        
        # Create test users
        self.admin_user = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            role=User.Role.ADMIN
        )
        
        self.coach_user = User.objects.create_user(
            email='coach@test.com',
            password='testpass123',
            first_name='Coach',
            last_name='User',
            role=User.Role.COACH
        )
        
        self.player_user = User.objects.create_user(
            email='player@test.com',
            password='testpass123',
            first_name='Player',
            last_name='User',
            role=User.Role.PLAYER
        )
        
        # Create test sport
        self.sport = Sport.objects.create(
            name='Basketball',
            description='Test basketball sport'
        )
        
        # Create coach profile
        self.coach_profile = Coach.objects.create(user=self.coach_user)
        
        # Create test team
        self.team = Team.objects.create(
            name='Test Team',
            abbreviation='TT',
            sport=self.sport,
            coach=self.coach_profile
        )
        
        # Create player profile
        self.player_profile = Player.objects.create(
            user=self.player_user,
            team=self.team,
            jersey_number=10,
            sport=self.sport,
            year_level='grade_10',
            course='stem'
        )
    
    def test_admin_overview_requires_admin_permission(self):
        """Test that admin overview requires admin permissions"""
        self.client.force_authenticate(user=self.player_user)
        url = reverse('dashboard-admin-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_admin_overview_with_admin_user(self):
        """Test admin overview with admin user"""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('dashboard-admin-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('system_overview', response.data)
        self.assertIn('recent_activity', response.data)
        self.assertIn('distribution_stats', response.data)
    
    def test_coach_overview_with_coach_user(self):
        """Test coach overview with coach user"""
        self.client.force_authenticate(user=self.coach_user)
        url = reverse('dashboard-coach-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('team_overview', response.data)
        self.assertIn('team_attendance', response.data)
    
    def test_coach_overview_without_coach_profile(self):
        """Test coach overview fails without coach profile"""
        self.client.force_authenticate(user=self.player_user)
        url = reverse('dashboard-coach-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    
    def test_player_overview_with_player_user(self):
        """Test player overview with player user"""
        self.client.force_authenticate(user=self.player_user)
        url = reverse('dashboard-player-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('personal_stats', response.data)
        self.assertIn('upcoming_sessions', response.data)
        self.assertIn('team_info', response.data)
    
    def test_player_overview_without_player_profile(self):
        """Test player overview fails without player profile"""
        # Create a user without player profile
        user_without_profile = User.objects.create_user(
            email='noprofile@test.com',
            password='testpass123',
            first_name='No',
            last_name='Profile',
            role=User.Role.PLAYER
        )
        
        self.client.force_authenticate(user=user_without_profile)
        url = reverse('dashboard-player-overview')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
    
    def test_player_progress_with_authenticated_user(self):
        """Test player progress with authenticated user"""
        self.client.force_authenticate(user=self.player_user)
        url = reverse('dashboard-player-progress')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('progress_summary', response.data)
        self.assertIn('metric_trends', response.data)
