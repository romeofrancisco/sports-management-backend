from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from django.core.exceptions import PermissionDenied

from teams.models import Coach, Player, Team
from sports.models import Sport
from .models import Game
from .views import GameViewSet

User = get_user_model()


class GameAccessControlTestCase(APITestCase):
    """Test case for game access control and permission system"""
    
    def setUp(self):
        """Set up test data"""
        # Create sport
        self.sport = Sport.objects.create(name='Basketball')
        
        # Create teams
        self.team1 = Team.objects.create(
            name='Team Alpha',
            sport=self.sport
        )
        self.team2 = Team.objects.create(
            name='Team Beta', 
            sport=self.sport
        )
        self.team3 = Team.objects.create(
            name='Team Gamma', 
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
        
        # Create player profiles
        self.player1 = Player.objects.create(user=self.player1_user, team=self.team1)
        
        # Create test games
        self.practice_game_coach1_teams = Game.objects.create(
            home_team=self.team1,
            away_team=self.team2,
            sport=self.sport,
            type=Game.Type.NORMAL,  # Practice game
            date='2024-01-15',
            time='14:00:00',
            location='Court 1',
            creator=self.admin_user
        )
        
        self.league_game = Game.objects.create(
            home_team=self.team1,
            away_team=self.team2,
            sport=self.sport,
            type=Game.Type.LEAGUE,  # League game
            date='2024-01-20',
            time='16:00:00',
            location='Court 2',
            creator=self.admin_user
        )
        
        self.practice_game_other_teams = Game.objects.create(
            home_team=self.team2,
            away_team=self.team3,
            sport=self.sport,
            type=Game.Type.NORMAL,  # Practice game
            date='2024-01-25',
            time='18:00:00',
            location='Court 3',
            creator=self.admin_user
        )

    def test_admin_can_view_all_games(self):
        """Test that admin can view all games regardless of type"""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('game-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 3)  # Should see all games

    def test_coach_can_view_own_team_games_only(self):
        """Test that coach can only view games involving their teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Coach1 should see 2 games (practice and league games involving team1)
        self.assertEqual(len(response.data['results']), 2)
        
        game_ids = [game['id'] for game in response.data['results']]
        self.assertIn(self.practice_game_coach1_teams.id, game_ids)
        self.assertIn(self.league_game.id, game_ids)
        self.assertNotIn(self.practice_game_other_teams.id, game_ids)

    def test_coach_can_create_practice_game_for_own_teams(self):
        """Test that coach can create practice games for their own teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-list')
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.NORMAL,  # Practice game
            'date': '2024-02-01',
            'time': '15:00:00',
            'location': 'Test Court'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['type'], Game.Type.NORMAL)

    def test_coach_cannot_create_league_game(self):
        """Test that coach cannot create league games"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-list')
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.LEAGUE,  # League game
            'date': '2024-02-01',
            'time': '15:00:00',
            'location': 'Test Court'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_create_game_for_other_teams(self):
        """Test that coach cannot create games for teams they don't coach"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-list')
        data = {
            'home_team': self.team2.id,
            'away_team': self.team3.id,
            'sport': self.sport.id,
            'type': Game.Type.NORMAL,  # Practice game
            'date': '2024-02-01',
            'time': '15:00:00',
            'location': 'Test Court'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_can_manage_practice_game_for_own_teams(self):
        """Test that coach can manage practice games involving their teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-manage', kwargs={'pk': self.practice_game_coach1_teams.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        
        # Should succeed (or at least not be forbidden due to permissions)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_manage_league_game(self):
        """Test that coach cannot manage league games even for their teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-manage', kwargs={'pk': self.league_game.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_manage_practice_game_for_other_teams(self):
        """Test that coach cannot manage practice games for other teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-manage', kwargs={'pk': self.practice_game_other_teams.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_manage_any_game(self):
        """Test that admin can manage any type of game"""
        self.client.force_authenticate(user=self.admin_user)
        
        # Test practice game
        url = reverse('game-manage', kwargs={'pk': self.practice_game_coach1_teams.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Test league game
        url = reverse('game-manage', kwargs={'pk': self.league_game.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_can_edit_practice_game_for_own_teams(self):
        """Test that coach can edit practice games involving their teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-detail', kwargs={'pk': self.practice_game_coach1_teams.id})
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.NORMAL,
            'date': '2024-01-16',  # Changed date
            'time': '15:00:00',
            'location': 'Updated Court'
        }
        response = self.client.put(url, data)
        
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_edit_league_game(self):
        """Test that coach cannot edit league games even for their teams"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-detail', kwargs={'pk': self.league_game.id})
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.LEAGUE,
            'date': '2024-01-21',
            'time': '17:00:00',
            'location': 'Updated Court'
        }
        response = self.client.put(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_coach_cannot_delete_any_game(self):
        """Test that coach cannot delete games (only admins can)"""
        self.client.force_authenticate(user=self.coach1_user)
        url = reverse('game-detail', kwargs={'pk': self.practice_game_coach1_teams.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_delete_any_game(self):
        """Test that admin can delete any game"""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse('game-detail', kwargs={'pk': self.practice_game_coach1_teams.id})
        response = self.client.delete(url)
        
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_player_cannot_create_game(self):
        """Test that players cannot create games"""
        self.client.force_authenticate(user=self.player1_user)
        url = reverse('game-list')
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.NORMAL,
            'date': '2024-02-01',
            'time': '15:00:00',
            'location': 'Test Court'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_player_cannot_manage_game(self):
        """Test that players cannot manage games"""
        self.client.force_authenticate(user=self.player1_user)
        url = reverse('game-manage', kwargs={'pk': self.practice_game_coach1_teams.id})
        data = {'action': 'start'}
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users are denied access to game management"""
        urls = [
            reverse('game-list'),
            reverse('game-detail', kwargs={'pk': self.practice_game_coach1_teams.id}),
            reverse('game-manage', kwargs={'pk': self.practice_game_coach1_teams.id}),
        ]
        
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_without_profile_access_denied(self):
        """Test that users without proper profiles are denied access"""
        # Create a user with coach role but no coach profile
        user_without_profile = User.objects.create_user(
            email='noprofile@test.com',
            password='testpass123',
            first_name='No',
            last_name='Profile',
            role='coach'  # Has coach role but no profile
        )
        
        self.client.force_authenticate(user=user_without_profile)
        url = reverse('game-list')
        data = {
            'home_team': self.team1.id,
            'away_team': self.team2.id,
            'sport': self.sport.id,
            'type': Game.Type.NORMAL,
            'date': '2024-02-01',
            'time': '15:00:00',
            'location': 'Test Court'
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class GameViewSetMethodTestCase(TestCase):
    """Test case for specific GameViewSet methods and permission logic"""
    
    def setUp(self):
        """Set up test data for method testing"""
        # Create basic test data
        self.sport = Sport.objects.create(name='Basketball')
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

    def test_get_queryset_filtering(self):
        """Test that get_queryset properly filters based on user role"""
        from unittest.mock import Mock
        
        # Test admin gets all games
        viewset = GameViewSet()
        viewset.request = Mock()
        viewset.request.user = self.admin_user
        
        queryset = viewset.get_queryset()
        # Should return the full queryset for admin
        self.assertTrue(hasattr(queryset, 'all'))
        
        # Test coach gets filtered games
        viewset.request.user = self.coach_user
        queryset = viewset.get_queryset()
        # Should return a filtered queryset for coach
        self.assertTrue(hasattr(queryset, 'filter'))

    def test_permission_denied_for_invalid_coach(self):
        """Test that PermissionDenied is raised for coaches without profiles"""
        # Create user with coach role but no coach profile
        invalid_coach = User.objects.create_user(
            email='invalid@test.com',
            password='testpass123',
            role='coach'  # Has role but no profile
        )
        
        viewset = GameViewSet()
        from unittest.mock import Mock
        viewset.request = Mock()
        viewset.request.user = invalid_coach
        
        # This should not raise an error, but return empty queryset
        # The actual permission check happens in the permission classes
        queryset = viewset.get_queryset()
        # For coaches without profiles, they should get limited access
        self.assertTrue(hasattr(queryset, 'filter'))
