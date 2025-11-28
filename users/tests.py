from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from teams.models import Team, Player
from google.oauth2 import id_token

from unittest.mock import patch

User = get_user_model()
class GoogleAndPasswordLoginTests(TestCase):
	def setUp(self):
		self.client = Client()
		from sports.models import Sport
		self.sport = Sport.objects.create(name='Test Sport', slug='test-sport')
		# Create a team for testing
		self.team = Team.objects.create(name='Test Team', abbreviation='TT', color='#000', sport=self.sport)

	def create_player_user(self, email='player@example.com', password='pass1234', with_team=False):
		user = User.objects.create(email=email, first_name='Test', last_name='Player', role=User.Role.PLAYER)
		user.set_password(password)
		user.save()
		Player.objects.create(user=user, height=170, weight=70, slug=f'player-{user.id}', team=self.team if with_team else None, jersey_number=1)
		return user

	def test_password_login_denied_for_player_without_team(self):
		user = self.create_player_user(with_team=False)
		login_url = reverse('users:login') if 'users:login' in [u.name for u in self.client.handler._urls] else '/api/login/'
		response = self.client.post('/api/login/', {'email': user.email, 'password': 'pass1234'}, content_type='application/json')
		self.assertEqual(response.status_code, 403)

	@patch('google.oauth2.id_token.verify_oauth2_token')
	def test_google_login_denied_for_player_without_team(self, mock_verify):
		user = self.create_player_user(with_team=False)
		# Mock Google verify to return the expected payload
		mock_verify.return_value = {
			'email': user.email,
			'aud': settings.GOOGLE_CLIENT_ID,
		}
		response = self.client.post('/api/google-signin/', {'credential': 'sometoken'}, content_type='application/json')
		self.assertEqual(response.status_code, 403)

	def test_password_login_allowed_for_player_with_team(self):
		user = self.create_player_user(with_team=True)
		response = self.client.post('/api/login/', {'email': user.email, 'password': 'pass1234'}, content_type='application/json')
		self.assertEqual(response.status_code, 200)

	@patch('google.oauth2.id_token.verify_oauth2_token')
	def test_google_login_allowed_for_player_with_team(self, mock_verify):
		user = self.create_player_user(with_team=True)
		mock_verify.return_value = {
			'email': user.email,
			'aud': settings.GOOGLE_CLIENT_ID,
		}
		response = self.client.post('/api/google-signin/', {'credential': 'sometoken'}, content_type='application/json')
		self.assertEqual(response.status_code, 200)
from django.test import TestCase

# Create your tests here.
