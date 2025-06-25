from django.db import transaction, connection
from rest_framework.exceptions import ValidationError
from games.models import Game, PlayerStat
from sports.models import SportStatType
import logging

logger = logging.getLogger(__name__)


class BulkRecordingService:
    """
    Optimized service for recording multiple stats in a single transaction
    Reduces database round trips and improves recording performance
    """
    
    
    def __init__(self, game_id):
        try:
            self.game = Game.objects.select_related('sport').get(pk=game_id)
        except Game.DoesNotExist:
            raise ValidationError({"game": "Game not found"})
    
    def validate_game_state(self):
        """Basic game state validation"""
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError({"game": "Game is not in progress"})
    
    @transaction.atomic
    def bulk_record(self, stats_data):
        """
        Record multiple stats in a single transaction
        
        Args:
            stats_data: List of stat dictionaries with keys:
                - player_id: Player ID
                - stat_type_id: SportStatType ID
                - timestamp: Optional timestamp (defaults to now)
        
        Returns:
            List of created PlayerStat instances
        """
        self.validate_game_state()
        
        if not stats_data:
            return []
        
        # Validate all data first before creating any records
        validated_stats = self._validate_bulk_data(stats_data)
        
        # Use bulk_create for optimal performance
        player_stats = []
        current_period = self.game.current_period
        
        for stat_data in validated_stats:
            player_stat = PlayerStat(
                player_id=stat_data['player_id'],
                game=self.game,
                stat_type_id=stat_data['stat_type_id'],
                period=current_period,
                timestamp=stat_data.get('timestamp')
            )
            player_stats.append(player_stat)
          # Disable signals during bulk creation to prevent duplicate score updates
        from django.db.models.signals import post_save, post_delete
        from games.signals import update_game_score
        
        # Disconnect the signal temporarily
        post_save.disconnect(update_game_score, sender=PlayerStat)
        post_delete.disconnect(update_game_score, sender=PlayerStat)
        
        try:
            # Bulk create all stats at once
            created_stats = PlayerStat.objects.bulk_create(
                player_stats, 
                batch_size=100,  # Process in batches of 100
                ignore_conflicts=False
            )
            
            # Update game scores once after all stats are recorded
            self.game.update_scores()
        finally:
            # Reconnect the signals
            post_save.connect(update_game_score, sender=PlayerStat)
            post_delete.connect(update_game_score, sender=PlayerStat)
        
        logger.info(f"Bulk recorded {len(created_stats)} stats for game {self.game.id}")
        return created_stats
    
    def _validate_bulk_data(self, stats_data):
        """
        Validate all stat data before processing
        """
        if len(stats_data) > 50:  # Prevent abuse
            raise ValidationError({"stats": "Cannot record more than 50 stats at once"})
        
        # Get all unique player and stat type IDs for validation
        player_ids = list(set(stat['player_id'] for stat in stats_data))
        stat_type_ids = list(set(stat['stat_type_id'] for stat in stats_data))
        
        # Validate players belong to game teams
        from teams.models import Player
        valid_players = Player.objects.filter(
            user_id__in=player_ids,
            team__in=[self.game.home_team, self.game.away_team]
        ).values_list('user_id', flat=True)
        
        invalid_players = set(player_ids) - set(valid_players)
        if invalid_players:
            raise ValidationError({
                "players": f"Players {invalid_players} are not part of this game"
            })
        
        # Validate stat types
        valid_stat_types = SportStatType.objects.filter(
            id__in=stat_type_ids,
            sport=self.game.sport,
            is_record=True
        ).values_list('id', flat=True)
        
        invalid_stat_types = set(stat_type_ids) - set(valid_stat_types)
        if invalid_stat_types:
            raise ValidationError({
                "stat_types": f"Stat types {invalid_stat_types} are invalid for this game"
            })
        
        return stats_data
    
    @transaction.atomic
    def bulk_record_optimized(self, stats_data):
        """
        Ultra-optimized bulk recording using raw SQL for maximum performance
        Use this for very large bulk operations (>20 stats)
        """
        self.validate_game_state()
        
        if not stats_data or len(stats_data) > 100:
            raise ValidationError({"stats": "Invalid stats data or too many stats"})
        
        validated_stats = self._validate_bulk_data(stats_data)
        current_period = self.game.current_period
        
        # Prepare bulk insert SQL
        values = []
        for stat_data in validated_stats:
            values.append(
                f"({stat_data['player_id']}, {self.game.id}, "
                f"{stat_data['stat_type_id']}, {current_period}, NOW())"
            )
          # Disable signals during raw SQL insertion to prevent duplicate score updates
        from django.db.models.signals import post_save, post_delete
        from games.signals import update_game_score
        
        # Disconnect the signal temporarily
        post_save.disconnect(update_game_score, sender=PlayerStat)
        post_delete.disconnect(update_game_score, sender=PlayerStat)
        
        try:
            # Execute bulk insert with raw SQL
            if values:
                sql = f"""
                    INSERT INTO games_playerstat (player_id, game_id, stat_type_id, period, timestamp)
                    VALUES {', '.join(values)}
                """
                
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                    affected_rows = cursor.rowcount
                  # Update game scores
                self.game.update_scores()
                
                logger.info(f"Bulk recorded {affected_rows} stats using raw SQL for game {self.game.id}")
                return {
                    'count': affected_rows,
                    'method': 'raw_sql'
                }
        finally:
            # Reconnect the signals
            post_save.connect(update_game_score, sender=PlayerStat)
            post_delete.connect(update_game_score, sender=PlayerStat)
        
        return {
            'count': 0,
            'method': 'raw_sql'
        }


class FastStatRecordingService:
    """
    Optimized service for single stat recording with minimal overhead
    """
    
    def __init__(self, validated_data):
        self.player = validated_data["player"]
        self.game = validated_data["game"]
        self.stat_type = validated_data["stat_type"]
    
    def validate(self):
        """Lightweight validation"""
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError({"game": "Game is not in progress"})
    @transaction.atomic
    def record_fast(self):
        """
        Optimized single stat recording
        - Minimal database queries
        - Efficient score updates
        """
        # Disable signals during stat creation to prevent duplicate score updates
        from django.db.models.signals import post_save, post_delete
        from games.signals import update_game_score
        
        # Disconnect the signal temporarily
        post_save.disconnect(update_game_score, sender=PlayerStat)
        post_delete.disconnect(update_game_score, sender=PlayerStat)
        
        try:
            # Create stat with minimal queries
            stat = PlayerStat.objects.create(
                player=self.player,
                game=self.game,
                stat_type=self.stat_type,
                period=self.game.current_period,
            )
            
            # Optimized score update - only update if it's a scoring stat
            if self.stat_type.is_points and self.stat_type.point_value > 0:
                self._update_score_efficiently()
        finally:
            # Reconnect the signals
            post_save.connect(update_game_score, sender=PlayerStat)
            post_delete.connect(update_game_score, sender=PlayerStat)
        
        return stat
    
    def _update_score_efficiently(self):
        """
        Update game scores without full recalculation for simple cases
        """
        point_value = self.stat_type.point_value
        
        if self.player.team == self.game.home_team:
            self.game.home_team_score += point_value
        elif self.player.team == self.game.away_team:
            self.game.away_team_score += point_value
        
        # Save only the score fields to minimize database writes
        self.game.save(update_fields=['home_team_score', 'away_team_score'])
