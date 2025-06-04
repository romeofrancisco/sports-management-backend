"""
Dashboard services package for sports management system.
Provides summary data and analytics for dashboard components.
"""

from .dashboard_summary_service import DashboardSummaryService
from .training_summary_service import TrainingSummaryService
from .league_summary_service import LeagueSummaryService
from .game_summary_service import GameSummaryService
from .analytics_service import AnalyticsService

__all__ = [
    'DashboardSummaryService',
    'TrainingSummaryService', 
    'LeagueSummaryService',
    'GameSummaryService',
    'AnalyticsService'
]
