# Service modules initialization

from .training_session_service import TrainingSessionService
from .player_training_service import PlayerTrainingService
from .multi_player_progress_service import MultiPlayerProgressService

__all__ = [
    'TrainingSessionService',
    'PlayerTrainingService',
    'MultiPlayerProgressService',
]
