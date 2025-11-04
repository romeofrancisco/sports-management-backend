from django.core.exceptions import ValidationError


class TournamentManagementService:
    def __init__(self, tournament):
        """Initialize the service with a tournament object.
        
        Args:
            tournament: Tournament object
        """
        self.tournament = tournament
    
    def manage_tournament(self, action_type):
        """Manage the state of a tournament based on the action type.
        
        Args:
            action_type: The type of action to perform (start, complete, pause, cancel)
            
        Returns:
            dict: A dictionary with a detail message
            
        Raises:
            ValidationError: If the action cannot be performed
        """
        if action_type == "start":
            self.tournament.start_tournament()
            return {"detail": "Tournament started."}
            
        elif action_type == "complete":
            self.tournament.complete_tournament()
            return {"detail": "Tournament completed."}
            
        elif action_type == "pause":
            self.tournament.pause_tournament()
            return {"detail": "Tournament paused."}
            
        elif action_type == "cancel":
            self.tournament.cancel_tournament()
            return {"detail": "Tournament canceled."}
            
        else:
            raise ValidationError("Invalid action.")
