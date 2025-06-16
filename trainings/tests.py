from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.core.exceptions import PermissionDenied
from unittest.mock import patch, Mock

from teams.models import Coach, Player, Team, Sport
from .models import (
    TrainingSession, PlayerTraining, TrainingMetric, 
    PlayerMetricRecord, TrainingCategory, MetricUnit
)
from .views import TrainingSessionViewSet, PlayerTrainingViewSet, PlayerMetricRecordViewSet

User = get_user_model()


class TrainingPermissionTestCase(APITestCase):
    """Test case for training-related permission system"""
    def setUp(self):
        """Set up test data"""
        # Create sport
        self.sport = Sport.objects.create(name='Football')
        
        # Create teams
        self.team1 = Team.objects.create(
            name='Team Alpha',
            sport=self.sport
        )
        self.team2 = Team.objects.create(
            name='Team Beta', 
            sport=self.sport
        )
        
        # Create admin user
        self.admin_user = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            first_name='Admin',
            last_name='User',
            role='admin'
        )
        
        # Create coach users
        self.coach1_user = User.objects.create_user(
            email='coach1@test.com',
            password='testpass123',
            first_name='Coach',
            last_name='One', 
            role='coach'
        )
        self.coach2_user = User.objects.create_user(
            email='coach2@test.com',
            password='testpass123',
            first_name='Coach',
            last_name='Two',
            role='coach'
        )
        
        # Create coach profiles
        self.coach1 = Coach.objects.create(user=self.coach1_user)
        self.coach1.teams.add(self.team1)
        
        self.coach2 = Coach.objects.create(user=self.coach2_user)
        self.coach2.teams.add(self.team2)
        
        # Create player users
        self.player1_user = User.objects.create_user(
            email='player1@test.com',
            password='testpass123',
            first_name='Player',
            last_name='One',
            role='player'
        )
        self.player2_user = User.objects.create_user(
            email='player2@test.com',
            password='testpass123',
            first_name='Player',
            last_name='Two',
            role='player'
        )
        
        # Create player profiles
        self.player1 = Player.objects.create(user=self.player1_user, team=self.team1)
        self.player2 = Player.objects.create(user=self.player2_user, team=self.team2)
        
        # Create training categories and metrics
        self.category = TrainingCategory.objects.create(
            name='Fitness',
            description='Physical fitness training'
        )
        self.metric_unit = MetricUnit.objects.create(
            name='Seconds',
            code='sec',
            description='Time measurement in seconds'
        )
        self.metric = TrainingMetric.objects.create(
            name='Sprint Time',
            description='40-yard dash time',
            category=self.category,
            unit=self.metric_unit
        )
        
        # Create training sessions
        self.session1 = TrainingSession.objects.create(
            title='Team Alpha Training',
            description='Regular practice session',
            date='2024-01-15',
            start_time='10:00:00',
            end_time='12:00:00',
            location='Field 1',
            team=self.team1
        )
        self.session2 = TrainingSession.objects.create(
            title='Team Beta Training',
            description='Regular practice session',
            date='2024-01-15',
            start_time='14:00:00',
            end_time='16:00:00',
            location='Field 2',
            team=self.team2
        )
        
        # Create player training records
        self.player_training1 = PlayerTraining.objects.create(
            player=self.player1,
            session=self.session1,
            attendance_status='present'
        )
        self.player_training2 = PlayerTraining.objects.create(
            player=self.player2,
            session=self.session2,
            attendance_status='present'
        )
        
        # Create metric records
        self.metric_record1 = PlayerMetricRecord.objects.create(
            player_training=self.player_training1,
            metric=self.metric,
            value=5.2
        )
        self.metric_record2 = PlayerMetricRecord.objects.create(
            player_training=self.player_training2,
            metric=self.metric,
            value=5.5
        )

    def test_admin_access_all_training_sessions(self):
        """Test that admin can access all training sessions"""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('trainingsession-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)  # Should see both sessions

    def test_coach_access_own_team_sessions_only(self):
        """Test that coach can only access their own team's training sessions"""
        # Coach 1 should only see team 1 sessions
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.session1.id)
        
        # Coach 2 should only see team 2 sessions
        self.client.force_authenticate(user=self.coach2_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.session2.id)

    def test_player_access_own_team_sessions_only(self):
        """Test that player can only access their own team's training sessions"""
        # Player 1 should only see team 1 sessions
        self.client.force_authenticate(user=self.player1_user)
        url = reverse('trainingsession-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.session1.id)

    def test_coach_cannot_access_other_team_session_detail(self):
        """Test that coach cannot access training session details from other teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-detail', kwargs={'pk': self.session2.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_can_create_session_for_own_team(self):
        """Test that coach can create training sessions for their own team"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-list')
        data = {
            'title': 'New Training Session',
            'description': 'Test session',
            'date': '2024-01-20',
            'start_time': '10:00:00',
            'end_time': '12:00:00',
            'location': 'Field 1',
            'team': self.team1.id
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_coach_cannot_create_session_for_other_team(self):
        """Test that coach cannot create training sessions for other teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-list')
        data = {
            'title': 'New Training Session',
            'description': 'Test session',
            'date': '2024-01-20',
            'start_time': '10:00:00',
            'end_time': '12:00:00',            'location': 'Field 2',
            'team': self.team2.id  # Team 2 is not coached by coach1
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_player_cannot_create_training_session(self):
        """Test that players cannot create training sessions"""
        self.client.force_authenticate(user=self.player1_user)
        url = reverse('trainingsession-list')
        data = {
            'title': 'New Training Session',
            'description': 'Test session',
            'date': '2024-01-20',
            'start_time': '10:00:00',
            'end_time': '12:00:00',
            'location': 'Field 1',
            'team': self.team1.id
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_can_update_own_team_session(self):
        """Test that coach can update training sessions for their own team"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-detail', kwargs={'pk': self.session1.id})
        data = {
            'title': 'Updated Training Session',
            'description': 'Updated description',
            'date': '2024-01-15',
            'start_time': '10:00:00',
            'end_time': '12:00:00',
            'location': 'Field 1',
            'team': self.team1.id
        }
        response = self.client.put(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Training Session')

    def test_coach_cannot_update_other_team_session(self):
        """Test that coach cannot update training sessions for other teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('trainingsession-detail', kwargs={'pk': self.session2.id})
        data = {
            'title': 'Updated Training Session',
            'description': 'Updated description',
            'date': '2024-01-15',
            'start_time': '14:00:00',
            'end_time': '16:00:00',
            'location': 'Field 2',
            'team': self.team2.id
        }
        response = self.client.put(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_player_training_access_permissions(self):
        """Test player training access permissions for different roles"""
        # Admin should see all player training records
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('playertraining-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        
        # Coach should only see their team's player training records
        self.client.force_authenticate(user=self.coach1_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.player_training1.id)
        
        # Player should only see their own training records
        self.client.force_authenticate(user=self.player1_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], self.player_training1.id)

    def test_metric_record_access_permissions(self):
        """Test player metric record access permissions for different roles"""
        # Admin should see all metric records
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('playermetricrecord-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)  # Assuming no pagination for metric records
        
        # Coach should only see their team's metric records
        self.client.force_authenticate(user=self.coach1_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        
        # Player should only see their own metric records
        self.client.force_authenticate(user=self.player1_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_administrative_viewsets_permissions(self):
        """Test that administrative viewsets (MetricUnit, TrainingCategory, TrainingMetric) 
        allow read access to all authenticated users but restrict write access to admins only"""
        
        # Test MetricUnit permissions
        metric_unit_url = reverse('metricunit-list')
        
        # All authenticated users should be able to read
        for user in [self.admin_user, self.coach1_user, self.player1_user]:
            self.client.force_authenticate(user=user)
            response = self.client.get(metric_unit_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Only admin should be able to create
        self.client.force_authenticate(user=self.coach1_user)
        data = {'name': 'Meters', 'code': 'm', 'description': 'Distance in meters'}
        response = self.client.post(metric_unit_url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(metric_unit_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users are denied access to all endpoints"""
        urls = [
            reverse('trainingsession-list'),
            reverse('playertraining-list'),
            reverse('playermetricrecord-list'),
            reverse('metricunit-list'),
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_without_profile_access_denied(self):
        """Test that users without proper profiles are denied access"""
        # Create a user with no coach or player profile
        regular_user = User.objects.create_user(
            email='regular@test.com',
            password='testpass123',
            first_name='Regular',
            last_name='User',
            role='player'  # Has player role but no profile
        )
        
        self.client.force_authenticate(user=regular_user)
        url = reverse('trainingsession-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TrainingViewSetMethodTestCase(TestCase):
    """Test case for specific viewset methods and permission logic"""
    
    def setUp(self):
        """Set up test data for method testing"""
        # Create basic test data similar to above
        self.sport = Sport.objects.create(name='Football', description='American Football')
        self.team = Team.objects.create(name='Test Team', sport=self.sport)
        
        self.admin_user = User.objects.create_user(
            email='admin@test.com',
            password='testpass123',
            role='admin'
        )
        
        self.coach_user = User.objects.create_user(
            email='coach@test.com', 
            password='testpass123',
            role='coach'
        )
        self.coach = Coach.objects.create(user=self.coach_user)
        self.coach.teams.add(self.team)
        
        self.player_user = User.objects.create_user(
            email='player@test.com',
            password='testpass123', 
            role='player'
        )
        self.player = Player.objects.create(user=self.player_user, team=self.team)

    def test_get_queryset_filtering(self):
        """Test that get_queryset properly filters based on user role"""
        from unittest.mock import Mock
        
        # Test admin gets all sessions
        viewset = TrainingSessionViewSet()
        viewset.request = Mock()
        viewset.request.user = self.admin_user
        
        # Mock the queryset to avoid database queries
        with patch.object(TrainingSession.objects, 'all') as mock_all:
            mock_all.return_value.order_by.return_value = Mock()
            result = viewset.get_queryset()
            mock_all.assert_called_once()
        
        # Test coach gets filtered sessions
        viewset.request.user = self.coach_user
        with patch.object(TrainingSession.objects, 'all') as mock_all:
            mock_queryset = Mock()
            mock_all.return_value.order_by.return_value = mock_queryset
            mock_queryset.filter.return_value = Mock()
            result = viewset.get_queryset()
            mock_queryset.filter.assert_called_once()
        
        # Test player gets filtered sessions
        viewset.request.user = self.player_user
        with patch.object(TrainingSession.objects, 'all') as mock_all:
            mock_queryset = Mock()
            mock_all.return_value.order_by.return_value = mock_queryset
            mock_queryset.filter.return_value = Mock()
            result = viewset.get_queryset()
            mock_queryset.filter.assert_called_once()

    def test_permission_denied_for_invalid_role(self):
        """Test that PermissionDenied is raised for users without proper roles"""
        # Create user without coach or player profile
        invalid_user = User.objects.create_user(
            email='invalid@test.com',
            password='testpass123',
            role='player'  # Has role but no profile
        )
        
        viewset = TrainingSessionViewSet()
        viewset.request = Mock()
        viewset.request.user = invalid_user
        
        with self.assertRaises(PermissionDenied):
            viewset.get_queryset()


# Additional test methods can be added here for more comprehensive testing
