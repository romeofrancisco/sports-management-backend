"""
Utility package for the sports management system.
Contains reusable helper functions for file uploads, data processing, etc.
"""
from .file_uploads import (
    generate_upload_path,
    team_logo_upload_path,
    player_photo_upload_path,
    coach_photo_upload_path,
    user_profile_upload_path,
    league_logo_upload_path,
    sport_banner_upload_path,
)

__all__ = [
    'generate_upload_path',
    'team_logo_upload_path',
    'player_photo_upload_path',
    'coach_photo_upload_path',
    'user_profile_upload_path',
    'league_logo_upload_path',
    'sport_banner_upload_path',
]
