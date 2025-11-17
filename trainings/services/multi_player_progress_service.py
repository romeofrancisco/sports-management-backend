
import time
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from django.db.models import Q
from teams.models import Player
from trainings.models import TrainingMetric
from trainings.utils import batch_fetch_record_data, calculate_player_improvement


class MultiPlayerProgressService:
    """
    Service class for handling multi-player progress data fetching and processing.
    Encapsulates the complex logic for efficiently fetching progress data for multiple players.
    """
    
    def __init__(self, request):
        """
        Initialize the service with request data.
        
        Args:
            request: Django request object containing query parameters
        """
        self.request = request
        self.start_time = time.time()
        
        # Extract and validate query parameters
        self._extract_parameters()
        self._validate_parameters()
    
    def _extract_parameters(self):
        """Extract and parse query parameters from the request."""
        self.team_slug = self.request.query_params.get('team')
        self.metric_id = self.request.query_params.get('metric_id')
        
        # Handle date parameters, filtering out 'undefined' values
        date_from_param = self.request.query_params.get('date_from')
        date_to_param = self.request.query_params.get('date_to')
        
        # Set to None if the parameter is 'undefined', 'null', or empty
        self.date_from = date_from_param if date_from_param not in ['undefined', 'null', '', None] else None
        self.date_to = date_to_param if date_to_param not in ['undefined', 'null', '', None] else None
        
        self.player_ids_param = self.request.query_params.get('player_ids', '')
        self.limit = self.request.query_params.get('limit')
        self.latest_only = self.request.query_params.get('latest_only', 'false').lower() == 'true'
        
        # Parse pagination parameters
        try:
            self.page_size = int(self.request.query_params.get('page_size', 50))
            self.page = int(self.request.query_params.get('page', 1))
        except ValueError:
            self.page_size = 50
            self.page = 1
            
        # Parse player_ids from comma-separated string
        self.player_ids = []
        if self.player_ids_param:
            self.player_ids = [pid for pid in self.player_ids_param.split(',') if pid]
    
    def _validate_parameters(self):
        """Validate required parameters."""
        if not self.metric_id:
            raise ValueError("Metric ID is required.")
            
        if not self.team_slug and not self.player_ids:
            raise ValueError("Either team slug or player IDs must be provided.")
    
    def _get_metric_data(self):
        """
        Get metric information for the requested metric.
        
        Returns:
            dict: Metric data including id, name, unit, and is_lower_better flag
            
        Raises:
            Http404: If metric is not found
        """
        try:
            # Handle "overall" metric specially
            if self.metric_id == 'overall':
                return {
                    'metric_id': 'overall',
                    'metric_name': 'Overall Performance',
                    'unit': '%',
                    'is_lower_better': False  # For overall, higher is always better
                }
            else:
                # For regular metrics, fetch from database
                metric = TrainingMetric.objects.select_related('metric_unit').only(
                    'name', 'is_lower_better', 'metric_unit__code'
                ).get(id=self.metric_id)
                
                return {
                    'metric_id': int(self.metric_id),
                    'metric_name': metric.name,
                    'unit': metric.metric_unit.code if metric.metric_unit else '-',
                    'is_lower_better': metric.is_lower_better,
                }
        except TrainingMetric.DoesNotExist:
            raise Http404("Metric not found.")
    
    def _build_players_query(self):
        """
        Build and optimize the players query based on parameters.
        
        Returns:
            QuerySet: Optimized players queryset
        """
        if self.team_slug:
            players_query = Player.objects.filter(team__slug=self.team_slug)
            if self.player_ids:
                players_query = players_query.filter(user_id__in=self.player_ids)
        else:
            players_query = Player.objects.filter(user_id__in=self.player_ids)
            
        # Optimize player query to fetch only needed fields 
        return players_query.select_related('team', 'user').only(
            'user_id', 'team_id', 'team__name', 'team__slug', 'user__first_name', 'user__last_name', 'user__profile'
        )
    def _paginate_players(self, players_query):
        """
        Apply pagination to the players query.
        
        Args:
            players_query: Players QuerySet to paginate
            
        Returns:
            tuple: (paginated_players_list, total_count)
        """
        # Count total players for pagination metadata
        total_players = players_query.count()
        
        # Apply pagination to players query for large datasets
        start_idx = (self.page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        paginated_players = list(players_query[start_idx:end_idx])
        
        # Return empty list if no players found - this is a valid scenario for teams with no players
        return paginated_players, total_players
    
    def _prepare_player_info(self, paginated_players):
        """
        Prepare the basic player information structure.
        
        Args:
            paginated_players: List of paginated player objects
            
        Returns:
            dict: Player info dictionary keyed by user_id
        """
        player_info = {}
        for player in paginated_players:
            player_id = player.user_id
            
            # Get profile picture URL with request context
            profile_url = None
            if player.user.profile:
                if hasattr(player.user.profile, 'url'):
                    profile_url = self.request.build_absolute_uri(player.user.profile.url)
            
            player_info[player_id] = {
                'user_id': player_id,
                'player_name': player.user.get_full_name(),
                'profile': profile_url,
                'team': player.team_id,
                'team_slug': player.team.slug if player.team else None,
                'team_name': player.team.name if player.team else None,
                'metrics_data': []
            }
        return player_info
    
    def _fetch_and_process_records(self, selected_player_ids, metric_data):
        """
        Fetch player metric records and process them.
        
        Args:
            selected_player_ids: List of player user IDs
            metric_data: Metric information dictionary
            
        Returns:
            tuple: (records_by_player, player_improvements)
        """
        # Fetch player metric records using optimized utility
        records_by_player = batch_fetch_record_data(
            selected_player_ids, 
            self.metric_id, 
            self.date_from, 
            self.date_to
        )
        
        # If latest_only is true, keep only the latest record for each player
        if self.latest_only:
            for player_id in records_by_player:
                if records_by_player[player_id]:
                    # Sort by date and keep only the most recent record
                    records_by_player[player_id].sort(key=lambda x: x['date'])
                    records_by_player[player_id] = [records_by_player[player_id][-1]]
          # Calculate overall improvement metrics for each player using batch ProgressService
        # This ensures consistency with the coach dashboard calculations
        from ..services.progress_service import ProgressService
        
        # Get Player instances for batch operations
        players_instances = Player.objects.filter(user_id__in=selected_player_ids)
        
        # Use batch methods for better performance
        overall_improvements = ProgressService.batch_calculate_overall_improvement(
            players_instances, self.date_from, self.date_to
        )
        recent_improvements = ProgressService.batch_calculate_recent_improvement(
            players_instances, self.date_from, self.date_to
        )
        best_performances = ProgressService.batch_find_best_performance(
            players_instances, self.date_from, self.date_to
        )
        
        # Convert to the expected format
        player_improvements = {}
        for player_id in selected_player_ids:
            player_improvements[player_id] = {
                'overall_improvement': overall_improvements.get(player_id),
                'recent_improvement': recent_improvements.get(player_id),
                'best_performance': best_performances.get(player_id)
            }
        
        return records_by_player, player_improvements
    
    def _build_response_data(self, player_info, records_by_player, player_improvements, metric_data, selected_player_ids):
        """
        Build the final response data structure.
        
        Args:
            player_info: Basic player information dictionary
            records_by_player: Player records organized by player ID
            player_improvements: Player improvement metrics
            metric_data: Metric information
            selected_player_ids: List of selected player IDs
            
        Returns:
            dict: Complete response data
        """
        # Bulk calculate training stats for all players to avoid N+1 queries
        from django.db.models import Count, Q, Max
        from ..models import Player, PlayerTraining, PlayerMetricRecord
        
        players = Player.objects.filter(user_id__in=selected_player_ids)
        
        # Training sessions stats - bulk calculate for all players
        training_query = PlayerTraining.objects.filter(player__in=players)
        if self.date_from:
            training_query = training_query.filter(session__date__gte=self.date_from)
        if self.date_to:
            training_query = training_query.filter(session__date__lte=self.date_to)
            
        training_stats = training_query.values('player__user_id').annotate(
            total_sessions=Count('id'),
            present_sessions=Count('id', filter=Q(attendance_status="present")),
            late_sessions=Count('id', filter=Q(attendance_status="late"))
        ).values('player__user_id', 'total_sessions', 'present_sessions', 'late_sessions')
        
        training_stats_dict = {stat['player__user_id']: stat for stat in training_stats}
        
        # Recent metrics count - bulk calculate
        recent_metrics_query = PlayerMetricRecord.objects.filter(player_training__player__in=players)
        if self.date_from:
            recent_metrics_query = recent_metrics_query.filter(recorded_at__gte=self.date_from)
        if self.date_to:
            recent_metrics_query = recent_metrics_query.filter(recorded_at__lte=self.date_to)
            
        recent_metrics_stats = recent_metrics_query.values('player_training__player__user_id').annotate(
            count=Count('id')
        ).values('player_training__player__user_id', 'count')
        
        recent_metrics_dict = {stat['player_training__player__user_id']: stat['count'] for stat in recent_metrics_stats}
        
        # Last training date - bulk calculate (within date range if specified)
        last_training_query = PlayerTraining.objects.filter(player__in=players)
        if self.date_from:
            last_training_query = last_training_query.filter(session__date__gte=self.date_from)
        if self.date_to:
            last_training_query = last_training_query.filter(session__date__lte=self.date_to)
            
        last_training_stats = last_training_query.values('player__user_id').annotate(
            last_date=Max('session__date')
        ).values('player__user_id', 'last_date')
        
        last_training_dict = {stat['player__user_id']: stat['last_date'] for stat in last_training_stats}
        
        # Build the final response structure
        for player_id, records in records_by_player.items():
            if player_id in player_info:
                # Create metric data structure for this player
                player_metric_data = dict(metric_data)
                
                # Attach the data points (records)
                player_metric_data['data_points'] = records
                
                # Add to player's metrics
                player_info[player_id]['metrics_data'] = [player_metric_data]
                  
                # Add improvement metrics if available
                if player_id in player_improvements:
                    improvement_data = player_improvements[player_id]
                    
                    # Get pre-calculated training stats
                    t_stats = training_stats_dict.get(player_id, {
                        'total_sessions': 0, 
                        'present_sessions': 0, 
                        'late_sessions': 0
                    })
                    
                    total_sessions = t_stats['total_sessions']
                    present_sessions = t_stats['present_sessions']
                    late_sessions = t_stats['late_sessions']
                    attended_sessions = present_sessions + late_sessions
                    attendance_rate = (attended_sessions / total_sessions * 100) if total_sessions > 0 else 0
                    
                    recent_metrics_count = recent_metrics_dict.get(player_id, 0)
                    last_training_date = last_training_dict.get(player_id)
                    
                    player_info[player_id].update({
                        'overall_improvement': improvement_data['overall_improvement'],
                        'recent_improvement': improvement_data['recent_improvement'],
                        'best_performance': improvement_data['best_performance'],
                        'training_count': len(records),
                        'total_sessions': total_sessions,
                        'attendance_rate': round(attendance_rate, 2),
                        'recent_metrics_count': recent_metrics_count,
                        'last_training_date': last_training_date
                    })
        
        # Format response with performance metadata
        response_data = {
            'results': player_info,
            'performance': {
                'execution_time_ms': round((time.time() - self.start_time) * 1000, 2),
                'metrics_evaluated': len(selected_player_ids),
                'data_points_count': sum(len(records) for records in records_by_player.values())
            }
        }
        return response_data
    
    def get_multi_player_progress(self):
        """
        Main method to fetch and process multi-player progress data.
        
        Returns:
            dict: Complete response data with player progress information
            
        Raises:
            ValueError: For validation errors
            Http404: For not found errors
        """
        # Get metric information
        metric_data = self._get_metric_data()
        
        # Build optimized players query
        players_query = self._build_players_query()
        
        # Apply pagination
        paginated_players, total_players = self._paginate_players(players_query)
        
        # Handle empty team case
        if not paginated_players:
            return {
                'results': {},
                'performance': {
                    'execution_time_ms': round((time.time() - self.start_time) * 1000, 2),
                    'metrics_evaluated': 0,
                    'data_points_count': 0
                }
            }
        
        # Get all user_ids from the paginated players
        selected_player_ids = [player.user_id for player in paginated_players]
        
        # Prepare response structure for all requested players
        player_info = self._prepare_player_info(paginated_players)
        
        # Fetch and process player metric records
        records_by_player, player_improvements = self._fetch_and_process_records(
            selected_player_ids, metric_data
        )
        
        # Build and return final response
        return self._build_response_data(
            player_info, records_by_player, player_improvements, 
            metric_data, selected_player_ids
        )
