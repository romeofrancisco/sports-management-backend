from django.db.models import Avg, Sum, Count, F
from django.db import models
from games.models import PlayerStat, Game
from sports.models import SportStatType
from teams.models import Player
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class PlayerImprovementService:
    """Service for tracking player improvements through games"""
    
    def __init__(self, player_id):
        self.player_id = player_id
        try:
            self.player = Player.objects.get(user_id=player_id)
        except Player.DoesNotExist:
            raise ValueError(f"Player with ID {player_id} not found")
    
    def get_game_by_game_improvement(self, stat_type_code, games_limit=10):
        """Track improvement for each game compared to previous games"""
        
        # Get the stat type
        try:
            stat_type = SportStatType.objects.get(code=stat_type_code)
        except SportStatType.DoesNotExist:
            return {"error": f"Stat type '{stat_type_code}' not found"}
        
        # Get completed games with this stat recorded for the player
        games_with_stats = Game.objects.filter(
            status=Game.Status.COMPLETED,
            playerstat__player=self.player,
            playerstat__stat_type=stat_type
        ).annotate(
            stat_count=Count('playerstat', filter=models.Q(
                playerstat__player=self.player,
                playerstat__stat_type=stat_type
            ))
        ).order_by('date')[:games_limit]
        
        if not games_with_stats.exists():
            return {"improvements": [], "message": "No games found with this stat recorded"}
        
        improvements = []
        for i, game in enumerate(games_with_stats):
            # Get total stats for this game
            current_stat_count = PlayerStat.objects.filter(
                game=game,
                player=self.player,
                stat_type=stat_type
            ).count()
            
            if i == 0:
                # First game has no previous comparison
                improvements.append({
                    'game_id': game.id,
                    'game_date': game.date,
                    'opponent': self._get_opponent_name(game),
                    'current_value': current_stat_count,
                    'improvement_from_previous': None,
                    'improvement_percentage': None,
                    'game_number': i + 1,
                    'trend': 'baseline'
                })
            else:
                previous_game = list(games_with_stats)[i - 1]
                previous_stat_count = PlayerStat.objects.filter(
                    game=previous_game,
                    player=self.player,
                    stat_type=stat_type
                ).count()
                
                improvement = current_stat_count - previous_stat_count
                improvement_percentage = 0
                if previous_stat_count > 0:
                    improvement_percentage = (improvement / previous_stat_count) * 100
                
                trend = 'improved' if improvement > 0 else 'declined' if improvement < 0 else 'same'
                
                improvements.append({
                    'game_id': game.id,
                    'game_date': game.date,
                    'opponent': self._get_opponent_name(game),
                    'current_value': current_stat_count,
                    'previous_value': previous_stat_count,
                    'improvement_from_previous': improvement,
                    'improvement_percentage': round(improvement_percentage, 2),
                    'game_number': i + 1,
                    'trend': trend
                })
        
        return {
            "improvements": improvements,
            "stat_type": {
                "code": stat_type.code,
                "name": stat_type.name,
                "display_name": stat_type.display_name or stat_type.name
            },
            "player": {
                "id": self.player.user.id,
                "name": self.player.user.get_full_name(),
                "jersey_number": self.player.jersey_number
            }
        }
    
    def get_running_average_improvement(self, stat_type_code, games_limit=10):
        """Track how player performs against their running average"""
        
        try:
            stat_type = SportStatType.objects.get(code=stat_type_code)
        except SportStatType.DoesNotExist:
            return {"error": f"Stat type '{stat_type_code}' not found"}
        
        games_with_stats = Game.objects.filter(
            status=Game.Status.COMPLETED,
            playerstat__player=self.player,
            playerstat__stat_type=stat_type
        ).order_by('date')[:games_limit]
        
        if not games_with_stats.exists():
            return {"improvements": [], "message": "No games found with this stat recorded"}
        
        improvements = []
        running_total = 0
        
        for i, game in enumerate(games_with_stats):
            current_stat_count = PlayerStat.objects.filter(
                game=game,
                player=self.player,
                stat_type=stat_type
            ).count()
            
            running_total += current_stat_count
            running_average = running_total / (i + 1)
            
            if i > 0:  # Need at least 2 games for comparison
                vs_average = current_stat_count - running_average
                vs_average_percentage = 0
                if running_average > 0:
                    vs_average_percentage = (vs_average / running_average) * 100
            else:
                vs_average = None
                vs_average_percentage = None
            
            improvements.append({
                'game_id': game.id,
                'game_date': game.date,
                'opponent': self._get_opponent_name(game),
                'current_value': current_stat_count,
                'running_average': round(running_average, 2),
                'vs_running_average': round(vs_average, 2) if vs_average is not None else None,
                'vs_average_percentage': round(vs_average_percentage, 2) if vs_average_percentage is not None else None,
                'game_number': i + 1
            })
        
        return {
            "improvements": improvements,
            "stat_type": {
                "code": stat_type.code,
                "name": stat_type.name,
                "display_name": stat_type.display_name or stat_type.name
            },
            "player": {
                "id": self.player.user.id,
                "name": self.player.user.get_full_name(),
                "jersey_number": self.player.jersey_number
            }
        }
    
    def get_improvement_streak(self, stat_type_code, max_games=5):
        """Get current improvement/decline streak"""
        
        try:
            stat_type = SportStatType.objects.get(code=stat_type_code)
        except SportStatType.DoesNotExist:
            return {"error": f"Stat type '{stat_type_code}' not found"}
        
        recent_games = Game.objects.filter(
            status=Game.Status.COMPLETED,
            playerstat__player=self.player,
            playerstat__stat_type=stat_type
        ).order_by('-date')[:max_games]
        
        if len(recent_games) < 2:
            return {
                'streak_type': None, 
                'streak_length': 0,
                'message': 'Need at least 2 games to determine streak'
            }
        
        # Get stat counts for each game
        game_stats = []
        for game in recent_games:
            stat_count = PlayerStat.objects.filter(
                game=game,
                player=self.player,
                stat_type=stat_type
            ).count()
            game_stats.append({
                'game': game,
                'value': stat_count,
                'date': game.date,
                'opponent': self._get_opponent_name(game)
            })
        
        # Reverse to get chronological order for streak calculation
        game_stats.reverse()
        
        streak_length = 0
        streak_type = None
        
        for i in range(len(game_stats) - 1):
            current = game_stats[i + 1]['value']
            previous = game_stats[i]['value']
            
            if current > previous:
                current_trend = 'improving'
            elif current < previous:
                current_trend = 'declining'
            else:
                current_trend = 'same'
            
            if streak_type is None:
                streak_type = current_trend
                streak_length = 1
            elif streak_type == current_trend:
                streak_length += 1
            else:
                break
        
        # Reverse back to most recent first for display
        game_stats.reverse()
        
        return {
            'streak_type': streak_type,
            'streak_length': streak_length,
            'latest_games': game_stats,
            'stat_type': {
                "code": stat_type.code,
                "name": stat_type.name,
                "display_name": stat_type.display_name or stat_type.name
            }
        }
    
    def get_multi_stat_improvement(self, stat_type_codes, games_limit=10):
        """Track improvements across multiple stats for comprehensive analysis"""
        
        # Validate stat types
        stat_types = {}
        for code in stat_type_codes:
            try:
                stat_types[code] = SportStatType.objects.get(code=code)
            except SportStatType.DoesNotExist:
                continue
        
        if not stat_types:
            return {"error": "No valid stat types found"}
        
        # Get games where player has recorded any of these stats
        games_with_stats = Game.objects.filter(
            status=Game.Status.COMPLETED,
            playerstat__player=self.player,
            playerstat__stat_type__in=stat_types.values()
        ).distinct().order_by('date')[:games_limit]
        
        if not games_with_stats.exists():
            return {"improvements": [], "message": "No games found with these stats recorded"}
        
        multi_stat_improvements = []
        
        for i, game in enumerate(games_with_stats):
            game_data = {
                'game_id': game.id,
                'game_date': game.date,
                'opponent': self._get_opponent_name(game),
                'game_number': i + 1,
                'stats': {}
            }
            
            total_improvement = 0
            stats_with_improvement = 0
            
            for code, stat_type in stat_types.items():
                current_count = PlayerStat.objects.filter(
                    game=game,
                    player=self.player,
                    stat_type=stat_type
                ).count()
                
                game_data['stats'][code] = {
                    'current_value': current_count,
                    'improvement_from_previous': None,
                    'improvement_percentage': None
                }
                
                if i > 0:
                    # Get previous game's stat
                    previous_game = list(games_with_stats)[i - 1]
                    previous_count = PlayerStat.objects.filter(
                        game=previous_game,
                        player=self.player,
                        stat_type=stat_type
                    ).count()
                    
                    improvement = current_count - previous_count
                    improvement_percentage = 0
                    if previous_count > 0:
                        improvement_percentage = (improvement / previous_count) * 100
                    
                    game_data['stats'][code].update({
                        'previous_value': previous_count,
                        'improvement_from_previous': improvement,
                        'improvement_percentage': round(improvement_percentage, 2)
                    })
                    
                    total_improvement += improvement_percentage
                    stats_with_improvement += 1
            
            # Calculate overall game improvement
            if stats_with_improvement > 0:
                game_data['overall_improvement_percentage'] = round(
                    total_improvement / stats_with_improvement, 2
                )
            else:
                game_data['overall_improvement_percentage'] = 0
            
            multi_stat_improvements.append(game_data)
        
        return {
            "improvements": multi_stat_improvements,
            "stat_types": {code: {
                "code": st.code,
                "name": st.name,
                "display_name": st.display_name or st.name
            } for code, st in stat_types.items()},
            "player": {
                "id": self.player.user.id,
                "name": self.player.user.get_full_name(),
                "jersey_number": self.player.jersey_number
            }
        }
    
    def get_season_progression(self, stat_type_code, season_id=None):
        """Track player progression throughout a season"""
        
        try:
            stat_type = SportStatType.objects.get(code=stat_type_code)
        except SportStatType.DoesNotExist:
            return {"error": f"Stat type '{stat_type_code}' not found"}
        
        # Filter by season if provided
        games_filter = {
            'status': Game.Status.COMPLETED,
            'playerstat__player': self.player,
            'playerstat__stat_type': stat_type
        }
        
        if season_id:
            games_filter['season_id'] = season_id
        
        season_games = Game.objects.filter(**games_filter).order_by('date')
        
        if not season_games.exists():
            return {"progression": [], "message": "No games found for this season"}
        
        progression = []
        season_total = 0
        
        for i, game in enumerate(season_games):
            game_stat_count = PlayerStat.objects.filter(
                game=game,
                player=self.player,
                stat_type=stat_type
            ).count()
            
            season_total += game_stat_count
            season_average = season_total / (i + 1)
            
            progression.append({
                'game_id': game.id,
                'game_date': game.date,
                'opponent': self._get_opponent_name(game),
                'game_value': game_stat_count,
                'season_total': season_total,
                'season_average': round(season_average, 2),
                'game_number': i + 1
            })
        
        return {
            "progression": progression,
            "season_summary": {
                "total_games": len(progression),
                "total_stats": season_total,
                "season_average": round(season_total / len(progression), 2) if progression else 0,
                "best_game": max(progression, key=lambda x: x['game_value']) if progression else None,
                "worst_game": min(progression, key=lambda x: x['game_value']) if progression else None
            },
            "stat_type": {
                "code": stat_type.code,
                "name": stat_type.name,
                "display_name": stat_type.display_name or stat_type.name
            }
        }
    
    def _get_opponent_name(self, game):
        """Get the opponent team name for the player's team"""
        if self.player.team == game.home_team:
            return game.away_team.name
        else:
            return game.home_team.name


class TeamPlayerImprovementService:
    """Service for tracking improvements across all players in a team"""
    
    def __init__(self, team_id):
        self.team_id = team_id
        
    def get_team_improvement_summary(self, stat_type_code, games_limit=5):
        """Get improvement summary for all players in the team"""
        
        try:
            stat_type = SportStatType.objects.get(code=stat_type_code)
        except SportStatType.DoesNotExist:
            return {"error": f"Stat type '{stat_type_code}' not found"}
        
        # Get all players in the team
        players = Player.objects.filter(team_id=self.team_id)
        
        team_improvements = []
        
        for player in players:
            service = PlayerImprovementService(player.user.id)
            improvement_data = service.get_game_by_game_improvement(
                stat_type_code, games_limit
            )
            
            if 'improvements' in improvement_data and improvement_data['improvements']:
                latest_improvement = improvement_data['improvements'][-1]
                team_improvements.append({
                    'player_id': player.user.id,
                    'player_name': player.user.get_full_name(),
                    'jersey_number': player.jersey_number,
                    'latest_value': latest_improvement.get('current_value', 0),
                    'latest_improvement': latest_improvement.get('improvement_from_previous'),
                    'latest_trend': latest_improvement.get('trend', 'no_data'),
                    'games_analyzed': len(improvement_data['improvements'])
                })
        
        # Sort by latest improvement (descending)
        team_improvements.sort(
            key=lambda x: x['latest_improvement'] or 0, 
            reverse=True
        )
        
        return {
            "team_improvements": team_improvements,
            "stat_type": {
                "code": stat_type.code,
                "name": stat_type.name,
                "display_name": stat_type.display_name or stat_type.name
            },
            "summary": {
                "total_players": len(team_improvements),
                "improving_players": len([p for p in team_improvements if p['latest_trend'] == 'improved']),
                "declining_players": len([p for p in team_improvements if p['latest_trend'] == 'declined']),
                "stable_players": len([p for p in team_improvements if p['latest_trend'] == 'same'])
            }
        }
