from django.db import transaction
from rest_framework.exceptions import ValidationError
from games.models import Game, PlayerStat



class RecordingService:
    def __init__(self, validated_data):
        self.player = validated_data["player"]
        self.game = validated_data["game"]
        self.stat_type = validated_data["stat_type"]

    def validate(self):
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError({"game": "Game is not in progress"})

    @transaction.atomic
    def record(self):
        # create the main stat
        stat = PlayerStat.objects.create(
            player=self.player,
            game=self.game,
            stat_type=self.stat_type,
            period=self.game.current_period,
        )

        # bump the game’s score aggregates
        self.game.update_scores()

        return stat
