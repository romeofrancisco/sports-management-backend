from django.core.exceptions import ValidationError

class SeasonManagementService:
    def __init__(self, season):
        """Initialize the service with a season object.
        
        Args:
            season: Season object
        """
        self.season = season
    
    def manage_season(self, action_type):
        """Manage the state of a season based on the action type.
        
        Args:
            action_type: The type of action to perform (start, complete, pause, cancel)
            
        Returns:
            dict: A dictionary with a detail message
            
        Raises:
            ValidationError: If the action cannot be performed
        """
        if action_type == "start":
            self.season.start_season()
            return {"detail": "Season started."}
            
        elif action_type == "complete":
            self.season.complete_season()
            return {"detail": "Season completed."}
            
        elif action_type == "pause":
            self.season.pause_season()
            return {"detail": "Season paused."}
            
        elif action_type == "cancel":
            self.season.cancel_season()
            return {"detail": "Season canceled."}
            
        else:
            raise ValidationError("Invalid action.")
