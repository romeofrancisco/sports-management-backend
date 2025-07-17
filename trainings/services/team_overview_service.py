from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from teams.models import Team, Player
from trainings.models import TrainingMetric, PlayerTraining
from trainings.utils import batch_fetch_record_data, calculate_player_improvement


class TeamOverviewService:
    """
    Service class for handling team overview statistics with weighted improvements.
    Provides comprehensive team performance analysis including player improvements,
    attendance rates, and best performing players.
    """
    
    def __init__(self):
        """Initialize the service."""
        self.today = timezone.now().date()
        self.three_months_ago = self.today - timedelta(days=90)
        self.date_from = self.three_months_ago.strftime('%Y-%m-%d')
        self.date_to = self.today.strftime('%Y-%m-%d')
    
    def get_team_overview(self, team_slug=None, metric_id=None, player_ids_param=None, user=None):
        """
        Get comprehensive team overview statistics.
        
        Args:
            team_slug: Team slug identifier (optional if player_ids_param provided)
            metric_id: Metric ID to analyze (required)
            player_ids_param: Comma-separated player IDs (optional)
            user: Request user for permission checking
            
        Returns:
            dict: Complete team overview data
            
        Raises:
            ValueError: For validation errors
            PermissionError: For access control violations
        """
        # Validate required parameters
        if not metric_id:
            raise ValueError("metric_id parameter is required")
        
        if not team_slug and not player_ids_param:
            raise ValueError("Either team or player_ids parameter is required")
        
        # Get players and team information
        players_list, team_name = self._get_players_and_team_info(
            team_slug, player_ids_param, user
        )
        
        player_ids = [player.user_id for player in players_list]
        
        # Handle empty team case
        if not player_ids:
            return self._create_empty_response(team_name, metric_id)
        
        # Get metric information
        metric_is_lower_better = self._get_metric_info(metric_id)
        
        # Fetch and process player data
        records_by_player = batch_fetch_record_data(
            player_ids, metric_id, self.date_from, self.date_to
        )
        
        player_improvements = calculate_player_improvement(
            records_by_player, metric_is_lower_better, metric_id
        )
        
        # Calculate team statistics
        team_stats = self._calculate_team_statistics(players_list, player_improvements)
        
        # Build and return response
        return self._build_response(team_name, player_ids, team_stats, metric_id)
    
    def _get_players_and_team_info(self, team_slug, player_ids_param, user):
        """
        Get players list and team information based on parameters and user permissions.
        
        Args:
            team_slug: Team slug identifier
            player_ids_param: Comma-separated player IDs
            user: Request user for permission checking
            
        Returns:
            tuple: (players_list, team_name)
            
        Raises:
            ValueError: For invalid player IDs format
            PermissionError: For access control violations
        """
        try:
            if team_slug:
                players_query = Player.objects.filter(team__slug=team_slug)
                
                # Get team info for response
                try:
                    team = Team.objects.get(slug=team_slug)
                    team_name = team.name
                except Team.DoesNotExist:
                    raise ValueError("Team not found")
                
                # Filter by specific player IDs if provided
                if player_ids_param:
                    player_ids = [int(id.strip()) for id in player_ids_param.split(',') if id.strip()]
                    players_query = players_query.filter(user_id__in=player_ids)
            else:
                player_ids = [int(id.strip()) for id in player_ids_param.split(',') if id.strip()]
                players_query = Player.objects.filter(user_id__in=player_ids)
                team_name = "Selected Players"
                
        except ValueError as e:
            if "invalid literal" in str(e):
                raise ValueError("Invalid player_ids format")
            raise e
        
        # Apply role-based access control
        players_query = self._apply_access_control(players_query, team_slug, user)
        
        # Get final players list
        players_list = list(players_query.select_related('user', 'team'))
        
        return players_list, team_name
    
    def _apply_access_control(self, players_query, team_slug, user):
        """
        Apply role-based access control to players query.
        
        Args:
            players_query: Initial players QuerySet
            team_slug: Team slug for team-based access
            user: Request user
            
        Returns:
            QuerySet: Filtered players query based on user permissions
            
        Raises:
            PermissionError: For insufficient permissions
        """
        if not user.is_admin:
            if hasattr(user, "coach_profile"):
                coach_teams = Team.objects.filter(
                    Q(head_coach=user.coach_profile) | Q(assistant_coach=user.coach_profile)
                )
                if team_slug:
                    team = Team.objects.get(slug=team_slug)
                    if team not in coach_teams:
                        raise PermissionError(
                            "You can only access overview data for your teams"
                        )
                else:
                    # For player_ids, ensure all players are from coach's teams
                    players_query = players_query.filter(team__in=coach_teams)
            elif hasattr(user, "player_profile"):
                # Players can only see their own team's overview
                if team_slug:
                    if user.player_profile.team.slug != team_slug:
                        raise PermissionError(
                            "You can only access your own team's overview data"
                        )
                else:
                    # For player_ids, players can only see their own data
                    players_query = players_query.filter(user_id=user.id)
            else:
                raise PermissionError(
                    "You don't have permission to access team overview data"
                )
        
        return players_query
    
    def _get_metric_info(self, metric_id):
        """
        Get metric information for improvement calculations.
        
        Args:
            metric_id: Metric ID or 'overall'
            
        Returns:
            bool: Whether lower values are better for this metric
            
        Raises:
            ValueError: If metric not found
        """
        try:
            if metric_id == 'overall':
                return False  # Overall performance is always "higher is better"
            else:
                metric = TrainingMetric.objects.get(id=metric_id)
                return metric.is_lower_better
        except TrainingMetric.DoesNotExist:
            raise ValueError("Metric not found")
    
    def _calculate_team_statistics(self, players_list, player_improvements):
        """
        Calculate comprehensive team statistics.
        
        Args:
            players_list: List of player objects
            player_improvements: Player improvement data from calculate_player_improvement
            
        Returns:
            dict: Comprehensive team statistics
        """
        players_with_data = 0
        overall_improvements = []
        recent_improvements = []
        best_player_data = None
        best_improvement_score = float('-inf')
        
        # Additional team statistics
        total_training_sessions = 0
        total_attendance_sessions = 0
        
        for player in players_list:
            player_id = player.user_id
            player_name = f"{player.user.first_name} {player.user.last_name}"
            
            # Process improvement data
            improvement_data = player_improvements.get(player_id)
            
            if improvement_data and improvement_data['overall_improvement'] is not None:
                players_with_data += 1
                
                # Collect overall improvements
                overall_improvement = improvement_data['overall_improvement']
                if overall_improvement and overall_improvement['percentage'] is not None:
                    overall_improvements.append(overall_improvement['percentage'])
                
                # Collect recent improvements
                recent_improvement = improvement_data['recent_improvement']
                if recent_improvement and recent_improvement['percentage'] is not None:
                    recent_improvements.append(recent_improvement['percentage'])
                
                # Find best performing player
                if (overall_improvement and 
                    overall_improvement['percentage'] is not None and 
                    overall_improvement['percentage'] > best_improvement_score):
                    best_improvement_score = overall_improvement['percentage']
                    best_player_data = {
                        'player_id': player_id,
                        'player_name': player_name,
                        'team_name': player.team.name if player.team else None,
                        'overall_improvement_percentage': overall_improvement['percentage'],
                        'recent_improvement_percentage': (
                            recent_improvement['percentage'] 
                            if recent_improvement and recent_improvement['percentage'] is not None 
                            else None
                        ),
                        'best_performance': improvement_data.get('best_performance')
                    }
            
            # Calculate attendance statistics
            attendance_stats = self._calculate_player_attendance(player)
            total_training_sessions += attendance_stats['total_sessions']
            total_attendance_sessions += attendance_stats['attended_sessions']
        
        return {
            'players_with_data': players_with_data,
            'overall_improvements': overall_improvements,
            'recent_improvements': recent_improvements,
            'best_player_data': best_player_data,
            'total_training_sessions': total_training_sessions,
            'total_attendance_sessions': total_attendance_sessions
        }
    
    def _calculate_player_attendance(self, player):
        """
        Calculate attendance statistics for a single player.
        
        Args:
            player: Player object
            
        Returns:
            dict: Player attendance statistics
        """
        try:
            player_trainings = PlayerTraining.objects.filter(
                player=player,
                session__date__gte=self.three_months_ago,
                session__date__lte=self.today
            )
            total_sessions = player_trainings.count()
            attended_sessions = player_trainings.filter(
                attendance_status__in=['present', 'late']
            ).count()
            
            return {
                'total_sessions': total_sessions,
                'attended_sessions': attended_sessions
            }
        except Exception:
            # Handle any potential errors gracefully
            return {
                'total_sessions': 0,
                'attended_sessions': 0
            }
    
    def _create_empty_response(self, team_name, metric_id):
        """
        Create response for empty team scenario.
        
        Args:
            team_name: Name of the team
            metric_id: Metric ID being analyzed
            
        Returns:
            dict: Empty team response data
        """
        return {
            'team_name': team_name,
            'number_of_players': 0,
            'recent_team_improvement': None,
            'overall_team_improvement': None,
            'best_player': None,
            'team_summary': {
                'date_range': {'from': self.date_from, 'to': self.date_to},
                'metric_analyzed': metric_id,
                'players_with_data': 0,
                'total_training_sessions': 0,
                'average_attendance_rate': 0.0
            }
        }
    
    def _build_response(self, team_name, player_ids, team_stats, metric_id):
        """
        Build the final response data structure.
        
        Args:
            team_name: Name of the team
            player_ids: List of player IDs
            team_stats: Calculated team statistics
            metric_id: Metric ID being analyzed
            
        Returns:
            dict: Complete response data
        """
        # Calculate team averages
        overall_team_improvement = (
            sum(team_stats['overall_improvements']) / len(team_stats['overall_improvements']) 
            if team_stats['overall_improvements'] else None
        )
        
        recent_team_improvement = (
            sum(team_stats['recent_improvements']) / len(team_stats['recent_improvements']) 
            if team_stats['recent_improvements'] else None
        )
        
        # Calculate average attendance rate
        average_attendance_rate = (
            (team_stats['total_attendance_sessions'] / team_stats['total_training_sessions'] * 100) 
            if team_stats['total_training_sessions'] > 0 else 0.0
        )
        
        return {
            'team_name': team_name,
            'number_of_players': len(player_ids),
            'recent_team_improvement': {
                'percentage': round(recent_team_improvement, 2) if recent_team_improvement is not None else None,
                'description': f"Average improvement over last 3 months ({len(team_stats['recent_improvements'])} players with data)"
            },
            'overall_team_improvement': {
                'percentage': round(overall_team_improvement, 2) if overall_team_improvement is not None else None,
                'description': f"Average improvement from first to latest records ({len(team_stats['overall_improvements'])} players with data)"
            },
            'best_player': team_stats['best_player_data'],
            'team_summary': {
                'date_range': {
                    'from': self.date_from,
                    'to': self.date_to,
                    'description': "Last 3 months"
                },
                'metric_analyzed': metric_id,
                'players_with_data': team_stats['players_with_data'],
                'total_players_analyzed': len(player_ids),
                'total_training_sessions': team_stats['total_training_sessions'],
                'average_attendance_rate': round(average_attendance_rate, 2),
                'improvement_data_available': {
                    'overall': len(team_stats['overall_improvements']),
                    'recent': len(team_stats['recent_improvements'])
                }
            }
        }
