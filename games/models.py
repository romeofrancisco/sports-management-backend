from django.db import models
from sports.models import Sport, SportStatType, Position
from django.db.models import Sum
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from leagues.models import League, Season


class GameCoachPermission(models.Model):
    """
    Model to track which coaches have permission to manage specific games
    """

    game = models.ForeignKey(
        "Game", on_delete=models.CASCADE, related_name="coach_permissions"
    )
    coach = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, related_name="game_permissions"
    )
    assigned_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="assigned_permissions",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["game", "coach"]
        indexes = [
            models.Index(fields=["game", "coach"]),
        ]

    def __str__(self):
        return f"{self.coach.get_full_name()} - {self.game}"


class Game(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        POSTPONED = "postponed", "Postponed"

    class Type(models.TextChoices):
        LEAGUE = "league", "League"
        TOURNAMENT = "tournament", "Tournament"
        PRACTICE = "practice", "Practice"

    sport = models.ForeignKey(Sport, on_delete=models.CASCADE)
    league = models.ForeignKey(League, on_delete=models.CASCADE, null=True)
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, null=True, related_name="games"
    )
    tournament = models.ForeignKey(
        "tournaments.Tournament", on_delete=models.CASCADE, null=True, blank=True, related_name="games"
    )
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.PRACTICE)
    is_recorded = models.BooleanField(default=False)
    creator = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="creator"
    )

    home_team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="home_games"
    )
    away_team = models.ForeignKey(
        "teams.Team", on_delete=models.CASCADE, related_name="away_games"
    )
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)

    # Add an explicit winner field that can be set directly
    winner_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="games_won",
    )

    date = models.DateField(null=True, blank=True, help_text="Game date")
    time = models.TimeField(null=True, blank=True, help_text="Game time")
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED, blank=True
    )

    current_period = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["home_team", "away_team"]),
        ]
        ordering = ["date"]

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')}: {self.home_team} vs {self.away_team}"

    def clean(self):
        errors = {}
        if self.home_team == self.away_team:
            errors["teams"] = "Home and away teams cannot be the same"
        if self.home_team.sport != self.sport or self.away_team.sport != self.sport:
            errors["sport"] = "Teams must belong to the game's sport"
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.type == self.Type.PRACTICE:
            self.is_recorded = False
        super().save(*args, **kwargs)

    def has_coach_permission(self, user):
        """
        Check if a coach has permission to manage this game
        - Admin users always have permission
        - For league games, check GameCoachPermission
        - For non-league games, allow team coaches
        """
        if user.is_admin:
            return True

        if not hasattr(user, "coach_profile"):
            return False

        # For league games, check explicit permissions
        if self.type == self.Type.LEAGUE:
            return self.coach_permissions.filter(coach=user).exists()

        # For non-league games, allow team coaches
        coach_profile = user.coach_profile
        
        # Check if coach is head coach or assistant coach of either team
        from teams.models import Team
        coach_teams = Team.objects.filter(
            models.Q(head_coach=coach_profile) | models.Q(assistant_coach=coach_profile)
        )
        
        return self.home_team in coach_teams or self.away_team in coach_teams

    def get_assigned_coaches(self):
        """Get all coaches assigned to manage this game"""
        return self.coach_permissions.select_related("coach__coach_profile").all()

    def assign_coach(self, coach, assigned_by):
        """Assign a coach to manage this game"""
        if self.type != self.Type.LEAGUE:
            raise ValidationError("Can only assign coaches to league games")

        permission, created = GameCoachPermission.objects.get_or_create(
            game=self, coach=coach, defaults={"assigned_by": assigned_by}
        )
        return permission, created

    def remove_coach(self, coach):
        """Remove coach permission for this game"""
        return self.coach_permissions.filter(coach=coach).delete()

    def update_scores(self):
        scores = self._calculate_team_scores()
        # Use save() instead of update() to trigger signals
        for field, value in scores.items():
            setattr(self, field, value)
        self.save(update_fields=list(scores.keys()))

    def update_scores_manual(self):
        """Update scores for scoreboard-only sports based on ScoreUpdate records"""
        if self.sport.requires_stats:
            # Use existing stat-based calculation
            self.update_scores()
            return

        # For scoreboard-only sports, calculate from ScoreUpdate records
        home_score = self.score_updates.filter(
            team=self.home_team,
            period__lte=self.current_period
        ).aggregate(total=Sum('points'))['total'] or 0

        away_score = self.score_updates.filter(
            team=self.away_team,
            period__lte=self.current_period
        ).aggregate(total=Sum('points'))['total'] or 0

        # For set-based sports, update current set scores
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            current_set_home = self.score_updates.filter(
                team=self.home_team,
                period=self.current_period
            ).aggregate(total=Sum('points'))['total'] or 0

            current_set_away = self.score_updates.filter(
                team=self.away_team,
                period=self.current_period
            ).aggregate(total=Sum('points'))['total'] or 0

            self.home_team_score = current_set_home
            self.away_team_score = current_set_away
        else:
            self.home_team_score = home_score
            self.away_team_score = away_score

        self.save(update_fields=['home_team_score', 'away_team_score', 'updated_at'])

    def add_score(self, team, points, period=None, updated_by=None):
        """
        Add points to a team's score
        Args:
            team: Team object
            points: Number of points to add (can be negative)
            period: Period number (defaults to current_period)
            updated_by: User who made the update
        """
        if self.sport.requires_stats:
            raise ValidationError("Use PlayerStat for stat-tracking sports")

        period = period or self.current_period
        
        ScoreUpdate.objects.create(
            game=self,
            team=team,
            points=points,
            period=period,
            updated_by=updated_by,
        )

    def set_score(self, home_score, away_score, updated_by=None):
        """
        Set exact scores for both teams (replaces current scores)
        """
        if self.sport.requires_stats:
            raise ValidationError("Use PlayerStat for stat-tracking sports")

        # Calculate the difference needed
        current_home = self.home_team_score
        current_away = self.away_team_score
        
        home_diff = home_score - current_home
        away_diff = away_score - current_away

        if home_diff != 0:
            ScoreUpdate.objects.create(
                game=self,
                team=self.home_team,
                points=home_diff,
                period=self.current_period,
                updated_by=updated_by,
            )

        if away_diff != 0:
            ScoreUpdate.objects.create(
                game=self,
                team=self.away_team,
                points=away_diff,
                period=self.current_period,
                updated_by=updated_by,
            )

    def validate_game_state(self, action):
        """
        Validate game state before proceeding to next period or completing game
        Returns None if valid, or a dict with {error: "message"} if invalid
        """
        sport = self.sport

        # Common validation for both actions
        if self.status != self.Status.IN_PROGRESS:
            return {"error": f"Game must be in progress to {action.replace('_', ' ')}"}

        # Set-based sports validation
        if sport.scoring_type == Sport.SCORING_TYPES.SETS:
            # Check win threshold for sets
            home_sets_won = self.sets.filter(winner=self.home_team).count()
            away_sets_won = self.sets.filter(winner=self.away_team).count()

            # For next period action
            if action == "next_period":
                # Check if we can proceed to next period
                if (
                    sport.max_period
                    and self.current_period >= sport.max_period
                    and not sport.has_overtime
                ):
                    return {
                        "error": "Cannot proceed beyond maximum periods without overtime"
                    }

                if sport.win_threshold and (
                    home_sets_won >= sport.win_threshold
                    or away_sets_won >= sport.win_threshold
                ):
                    return {
                        "error": "Game should be completed as win threshold has been reached"
                    }

                # Check win points threshold for current set
                if sport.win_points_threshold and self:
                    if (
                        self.home_team_score < sport.win_points_threshold
                        and self.away_team_score < sport.win_points_threshold
                    ):
                        return {
                            "error": f"Neither team has reached the win points threshold of {sport.win_points_threshold}"
                        }

                    # Check win margin if specified
                    if sport.win_margin:
                        score_diff = abs(self.home_team_score - self.away_team_score)
                        if (
                            max(self.home_team_score, self.away_team_score)
                            >= sport.win_points_threshold
                            and score_diff < sport.win_margin
                        ):
                            return {
                                "error": f"Score difference must be at least {sport.win_margin} to complete the set"
                            }

        # Point-based sports validation
        else:
            if (
                action == "complete"
                and not sport.has_tie
                and self.home_team_score == self.away_team_score
            ):
                return {
                    "error": "Cannot complete game with tied score - this sport doesn't allow ties"
                }

            # Overtime validation - check if trying to go to overtime
            if action == "next_period" and sport.has_period and sport.max_period:
                # Check if we're at max regular periods or already in overtime
                is_overtime_now = self.current_period > sport.max_period
                reaching_max_period = self.current_period == sport.max_period
                is_tied = self.home_team_score == self.away_team_score

                # Case 1: Not in overtime yet but reaching max period
                if reaching_max_period and sport.has_overtime:
                    if not is_tied:
                        return {
                            "error": "Cannot proceed to overtime when scores aren't tied"
                        }

                # Case 2: Already in overtime and checking if we can extend to another OT
                elif is_overtime_now:
                    # For multiple overtimes, we need to be in OT already AND have tied scores
                    if sport.has_overtime and is_tied:
                        pass  # Allow advancing to another overtime period
                    else:
                        return {"error": "Game should be completed after overtime"}

            # For point-based sports with periods, validate max periods reached
            if action == "complete" and sport.has_period and sport.max_period:
                if self.current_period < sport.max_period:
                    return {
                        "error": f"Game cannot be completed before reaching maximum period ({sport.max_period})"
                    }

            if sport.win_points_threshold and action == "complete":
                if (
                    self.home_team_score < sport.win_points_threshold
                    and self.away_team_score < sport.win_points_threshold
                ):
                    return {
                        "error": f"Neither team has reached the win points threshold of {sport.win_points_threshold}"
                    }

                if sport.win_margin:
                    score_diff = abs(self.home_team_score - self.away_team_score)
                    if (
                        max(self.home_team_score, self.away_team_score)
                        >= sport.win_points_threshold
                        and score_diff < sport.win_margin
                    ):
                        return {
                            "error": f"Score difference must be at least {sport.win_margin} to win"
                        }

        return None  # No errors

    def _calculate_team_scores(self):
        # Use select_related and prefetch_related for better performance
        stats_queryset = PlayerStat.objects.select_related(
            'player__team', 'stat_type'
        ).filter(game=self)
        
        # Filter by current period if it's a set-based sport
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            # Ensure set exists for current period
            if not self.sets.filter(period=self.current_period).exists():
                GameSet.objects.create(
                    game=self,
                    period=self.current_period,
                    home_team_score=0,
                    away_team_score=0,
                    winner=None,
                )
            stats_queryset = stats_queryset.filter(period=self.current_period)
        
        # Filter for stats that have point values
        stats_queryset = stats_queryset.filter(stat_type__point_value__gt=0)
        
        # Calculate scores using aggregation
        home_positive = stats_queryset.filter(
            player__team=self.home_team, 
            stat_type__is_negative=False
        ).aggregate(total=Sum("stat_type__point_value"))["total"] or 0
        
        home_negative = stats_queryset.filter(
            player__team=self.away_team, 
            stat_type__is_negative=True
        ).aggregate(total=Sum("stat_type__point_value"))["total"] or 0
        
        away_positive = stats_queryset.filter(
            player__team=self.away_team, 
            stat_type__is_negative=False
        ).aggregate(total=Sum("stat_type__point_value"))["total"] or 0
        
        away_negative = stats_queryset.filter(
            player__team=self.home_team, 
            stat_type__is_negative=True
        ).aggregate(total=Sum("stat_type__point_value"))["total"] or 0
        
    def update_scores_incremental(self, stat, operation='add'):
        """
        Update scores incrementally when a stat is added/removed
        Much faster than full recalculation
        
        Args:
            stat: PlayerStat instance
            operation: 'add' or 'remove'
        """
        point_value = stat.stat_type.point_value
        team = stat.player.team
        
        # Handle set-based sports (only current period)
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            if stat.period != self.current_period:
                return  # Don't update if not current period
        
        # Calculate score change
        if operation == 'add':
            score_change = point_value
        elif operation == 'remove':
            score_change = -point_value
        else:
            return
        
        # Apply to appropriate team
        if team == self.home_team:
            self.home_team_score = max(0, self.home_team_score + score_change)
        elif team == self.away_team:
            self.away_team_score = max(0, self.away_team_score + score_change)
        
        # Save without triggering signals
        self.save(update_fields=['home_team_score', 'away_team_score', 'updated_at'])

    def start_game(self):
        if self.status != self.Status.SCHEDULED:
            raise ValidationError(
                {"error": "Game can only start from scheduled status"}
            )
        if not self.date:
            raise ValidationError(
                {"error": "Please specify a start date before launching the game."}
            )

        # Only validate lineup for stat-tracking sports
        if self.sport.requires_stats:
            self.validate_starting_lineup()

        # Initialize first set for set-based sports
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            GameSet.objects.create(
                game=self, period=1, home_team_score=0, away_team_score=0, winner=None
            )

        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        self.save()

    def complete_game(self):
        """Complete the game with sport-specific validation"""
        if error := self.validate_game_state("complete"):
            raise ValidationError(error)

        sport = self.sport

        # For set-based sports, ensure current set is saved FIRST
        if sport.scoring_type == Sport.SCORING_TYPES.SETS:
            existing_set = self.sets.filter(period=self.current_period).first()
            if existing_set:
                existing_set.home_team_score = self.home_team_score
                existing_set.away_team_score = self.away_team_score
                existing_set.winner = (
                    self.home_team
                    if self.home_team_score > self.away_team_score
                    else (
                        self.away_team
                        if self.away_team_score > self.home_team_score
                        else None
                    )
                )
                existing_set.save()

            # Now perform validation AFTER saving the current set
            home_sets_won = self.sets.filter(winner=self.home_team).count()
            away_sets_won = self.sets.filter(winner=self.away_team).count()

            # Check if win threshold is met
            if sport.win_threshold:
                if (
                    home_sets_won < sport.win_threshold
                    and away_sets_won < sport.win_threshold
                ):
                    raise ValidationError(
                        {"error": f"Neither team has won {sport.win_threshold} sets"}
                    )

            # Check if current set is complete only if it's not already won/lost
            current_set = self.sets.filter(period=self.current_period).first()
            if current_set and not current_set.winner and sport.win_points_threshold:
                if (
                    current_set.home_team_score < sport.win_points_threshold
                    and current_set.away_team_score < sport.win_points_threshold
                ):
                    raise ValidationError(
                        {
                            "error": f"Current set hasn't reached {sport.win_points_threshold} points"
                        }
                    )

                if sport.win_margin:
                    score_diff = abs(
                        current_set.home_team_score - current_set.away_team_score
                    )
                    if score_diff < sport.win_margin:
                        raise ValidationError(
                            {
                                "error": f"Need {sport.win_margin} point margin to finish set"
                            }
                        )

        self.status = self.Status.COMPLETED
        self.ended_at = timezone.now()
        self.duration = self.ended_at - self.started_at if self.started_at else None
        self.save(update_fields=["status", "ended_at", "duration", "updated_at"])

    def next_period(self):
        """Proceed to next period with sport-specific validation"""
        # Direct check for overtime limitations - only checks if scores aren't tied
        if (
            self.sport.scoring_type == Sport.SCORING_TYPES.POINTS
            and self.sport.has_period
            and self.current_period >= self.sport.max_period
            and self.home_team_score != self.away_team_score
        ):
            raise ValidationError(
                {"error": "Cannot proceed to more overtime - scores not tied"}
            )

        # Regular validation through validate_game_state
        if error := self.validate_game_state("next_period"):
            raise ValidationError(error)

        # For set-based sports, save current set results
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            existing_set = self.sets.filter(period=self.current_period).first()
            if existing_set:
                existing_set.home_team_score = self.home_team_score
                existing_set.away_team_score = self.away_team_score
                existing_set.winner = (
                    self.home_team
                    if self.home_team_score > self.away_team_score
                    else (
                        self.away_team
                        if self.away_team_score > self.home_team_score
                        else None
                    )
                )
                existing_set.save()

            # Check if game should end based on sets won
            home_sets_won = self.sets.filter(winner=self.home_team).count()
            away_sets_won = self.sets.filter(winner=self.away_team).count()

            if self.sport.win_threshold and (
                home_sets_won >= self.sport.win_threshold
                or away_sets_won >= self.sport.win_threshold
            ):
                return self.complete_game()

        # Move to next period
        self.current_period += 1
        updates = ["current_period"]

        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            # Reset game score for new set
            self.home_team_score = 0
            self.away_team_score = 0
            updates += ["home_team_score", "away_team_score"]

            # Create new set if needed
            if not self.sets.filter(period=self.current_period).exists():
                GameSet.objects.create(
                    game=self,
                    period=self.current_period,
                    home_team_score=0,
                    away_team_score=0,
                    winner=None,
                )

        self.save(update_fields=updates)

    def validate_starting_lineup(self):
        sport = self.sport
        
        # Skip lineup validation for scoreboard-only sports
        if not sport.requires_stats:
            return
        
        errors = []

        for team, label in [(self.home_team, "Home"), (self.away_team, "Away")]:
            count = self.starting_lineup.filter(team=team).count()
            if count != sport.max_players_on_field:
                errors.append(
                    f"{label} team needs exactly {sport.max_players_on_field} starters"
                )

        if errors:
            raise ValidationError(" ".join(errors))

    def get_lineup_status(self):
        return {
            "home_ready": self._is_team_ready(self.home_team),
            "away_ready": self._is_team_ready(self.away_team),
        }

    def _is_team_ready(self, team):
        return (
            self.starting_lineup.filter(team=team).count()
            == self.sport.max_players_on_field
        )

    def get_current_players(self, team):
        starters = self.starting_lineup.filter(
            team=team, is_starting=True
        ).select_related("player")
        current = {s.player_id: s for s in starters}

        substitutions = self.substitutions.filter(
            substitute_in__team=team, period__lte=self.current_period
        ).order_by("timestamp")

        for sub in substitutions:
            if sub.substitute_out_id in current:
                current[sub.substitute_in_id] = StartingLineup(
                    player=sub.substitute_in, team=team, game=self, is_starting=False
                )
                del current[sub.substitute_out_id]

        return list(current.values())

    @property
    def winner(self):
        # First, check if we have an explicitly set winner
        if self.winner_team is not None:
            return self.winner_team

        # If no explicit winner is set, calculate based on scores
        if self.status != self.Status.COMPLETED:
            return None  # Match is still in progress

        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            home_sets = self.sets.filter(winner=self.home_team).count()
            away_sets = self.sets.filter(winner=self.away_team).count()

            # If a team has reached the win threshold
            if home_sets >= self.sport.win_threshold:
                return self.home_team
            elif away_sets >= self.sport.win_threshold:
                return self.away_team

            # If no tie is allowed and neither team has reached the win threshold
            if not self.sport.has_tie:
                return None  # No winner yet, match is ongoing (no tie allowed)

            # If tie is allowed
            return None  # Tie, no winner

        else:
            # Points-based scoring logic
            if self.home_team_score > self.away_team_score:
                return self.home_team
            elif self.away_team_score > self.home_team_score:
                return self.away_team
            return None  # Tie

    @winner.setter
    def winner(self, team):
        """Set the winner_team field when winner property is assigned to."""
        self.winner_team = team

    @property
    def score_summary(self):
        # Common base structure
        summary = {
            "periods": [],  # Array of period/set scores
            "current_period": self.current_period,
        }

        # For set-based sports (volleyball, tennis, etc.)
        if self.sport.scoring_type == Sport.SCORING_TYPES.SETS:
            sets = self.sets.all().order_by("period")
            summary["periods"] = [
                {
                    "period": s.period,
                    "label": s.period,
                    "home": s.home_team_score,
                    "away": s.away_team_score,
                    "completed": True,
                    "winner": s.winner.id if s.winner else None,
                }
                for s in sets
            ]
            summary["total"] = {
                "home": self.sets.filter(winner=self.home_team).count(),
                "away": self.sets.filter(winner=self.away_team).count(),
                "difference": abs(
                    self.sets.filter(winner=self.home_team).count()
                    - self.sets.filter(winner=self.away_team).count()
                ),
            }
            summary["win_threshold"] = self.sport.win_threshold

        # For point-based sports with periods (basketball, etc.)
        elif (
            self.sport.scoring_type == Sport.SCORING_TYPES.POINTS
            and self.sport.has_period
        ):
            for period in range(1, self.current_period + 1):
                # Determine period label
                if period <= self.sport.max_period:
                    label = period
                else:
                    ot_number = period - self.sport.max_period
                    label = (
                        "OT" if ot_number == 1 else f"{ot_number}OT"
                    )  # OT, 2OT, 3OT etc.

                # Calculate home team points
                home_positive_points = (
                    PlayerStat.objects.filter(
                        game=self,
                        player__team=self.home_team,
                        stat_type__point_value__gt=0,
                        stat_type__is_negative=False,
                        period=period,
                    ).aggregate(total=Sum("stat_type__point_value"))["total"]
                    or 0
                )

                away_negative_points = (
                    PlayerStat.objects.filter(
                        game=self,
                        player__team=self.away_team,
                        stat_type__point_value__gt=0,
                        stat_type__is_negative=True,
                        period=period,
                    ).aggregate(total=Sum("stat_type__point_value"))["total"]
                    or 0
                )

                home_score = home_positive_points + away_negative_points

                # Calculate away team points
                away_positive_points = (
                    PlayerStat.objects.filter(
                        game=self,
                        player__team=self.away_team,
                        stat_type__point_value__gt=0,
                        stat_type__is_negative=False,
                        period=period,
                    ).aggregate(total=Sum("stat_type__point_value"))["total"]
                    or 0
                )

                home_negative_points = (
                    PlayerStat.objects.filter(
                        game=self,
                        player__team=self.home_team,
                        stat_type__point_value__gt=0,
                        stat_type__is_negative=True,
                        period=period,
                    ).aggregate(total=Sum("stat_type__point_value"))["total"]
                    or 0
                )

                away_score = away_positive_points + home_negative_points

                summary["periods"].append(
                    {
                        "period": period,
                        "label": label,
                        "home": home_score,
                        "away": away_score,
                        "completed": period < self.current_period,
                        "winner": None,  # Winner determined by total score
                    }
                )

            # Add total scores
            summary["total"] = {
                "home": self.home_team_score,
                "away": self.away_team_score,
                "difference": abs(self.home_team_score - self.away_team_score),
            }

        # Default for point-based sports without periods
        else:
            summary["total"] = {
                "home": self.home_team_score,
                "away": self.away_team_score,
                "difference": abs(self.home_team_score - self.away_team_score),
            }

        return summary


# For Set Type Sports
class GameSet(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="sets")
    period = models.PositiveIntegerField()
    home_team_score = models.PositiveIntegerField(default=0)
    away_team_score = models.PositiveIntegerField(default=0)
    winner = models.ForeignKey(
        "teams.Team", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        unique_together = ("game", "period")
        ordering = ["period"]

class ScoreUpdate(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="score_updates")
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE)
    points = models.IntegerField(help_text="Points added (can be negative for corrections)")
    period = models.PositiveIntegerField()
    updated_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, related_name="score_updates"
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["game", "team"]),
            models.Index(fields=["period"]),
        ]

    def clean(self):
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError("Scores can only be updated for in-progress games")
        if self.team not in [self.game.home_team, self.game.away_team]:
            raise ValidationError("Team is not part of this game")
        if self.game.sport.requires_stats:
            raise ValidationError("Manual score updates not allowed for stat-tracking sports")
        
        # Validate game rules even for scoreboard-only sports
        game = self.game
        sport = game.sport
        
        # Calculate what the new scores would be after this update
        if self.team == game.home_team:
            new_home_score = game.home_team_score + self.points
            new_away_score = game.away_team_score
        else:
            new_home_score = game.home_team_score
            new_away_score = game.away_team_score + self.points
            
        # Prevent negative scores
        if new_home_score < 0 or new_away_score < 0:
            raise ValidationError("Score cannot be negative")

        # Validate scoring rules based on sport type
        # Check if a team has ALREADY won before this score update
        if sport.scoring_type == Sport.SCORING_TYPES.SETS:
            if sport.win_points_threshold and sport.win_margin:
                if (
                    game.home_team_score >= sport.win_points_threshold
                    and (game.home_team_score - game.away_team_score) >= sport.win_margin
                ):
                    raise ValidationError(
                        "Home team has already won this set, please advance to the next set"
                    )
                if (
                    game.away_team_score >= sport.win_points_threshold
                    and (game.away_team_score - game.home_team_score) >= sport.win_margin
                ):
                    raise ValidationError(
                        "Away team has already won this set, please advance to the next set"
                    )
        else:
            # Point-based sports validation
            if sport.win_points_threshold and sport.win_margin:
                if (
                    game.home_team_score >= sport.win_points_threshold
                    and (game.home_team_score - game.away_team_score) >= sport.win_margin
                ):
                    raise ValidationError(
                        "Home team has already won the game"
                    )
                if (
                    game.away_team_score >= sport.win_points_threshold
                    and (game.away_team_score - game.home_team_score) >= sport.win_margin
                ):
                    raise ValidationError(
                        "Away team has already won the game"
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        # Update game scores after saving
        self.game.update_scores_manual()

    def __str__(self):
        return f"{self.team.name}: {'+' if self.points >= 0 else ''}{self.points} pts"

class PlayerStat(models.Model):
    player = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="player_stats"
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    stat_type = models.ForeignKey(SportStatType, on_delete=models.CASCADE)
    period = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["game", "player"]),
        ]
        ordering = ["-timestamp"]

    def clean(self):
        # Check if sport requires stats
        if not self.game.sport.requires_stats:
            raise ValidationError(
                "This sport does not support individual player statistics"
            )
        
        if self.game.status != Game.Status.IN_PROGRESS:
            raise ValidationError(
                "Stats can only be recorded for in-progress games"
            )
        if self.period > self.game.current_period:
            raise ValidationError("Cannot record stats for future periods")
        if self.player.team not in [self.game.home_team, self.game.away_team]:
            raise ValidationError("Player is not part of this game")
        if self.stat_type.sport != self.game.sport:
            raise ValidationError("Stat type doesn't match game sport")

        # New validation: Check if win conditions are already met
        game = self.game
        sport = game.sport

        if sport.scoring_type == Sport.SCORING_TYPES.SETS:
            if sport.win_points_threshold and sport.win_margin:
                if (
                    game.home_team_score >= sport.win_points_threshold
                    and (game.home_team_score - game.away_team_score)
                    >= sport.win_margin
                ):
                    raise ValidationError(
                        "Home team has already won this set, Please advance to next the set"
                    )
                if (
                    game.away_team_score >= sport.win_points_threshold
                    and (game.away_team_score - game.home_team_score)
                    >= sport.win_margin
                ):                    raise ValidationError(
                        "Away team has already won this set, Please advance to next the set"
                    )
        else:
            # Point-based sports validation
            if sport.win_points_threshold and sport.win_margin:
                if (
                    game.home_team_score >= sport.win_points_threshold
                    and (game.home_team_score - game.away_team_score)
                    >= sport.win_margin
                ):                    raise ValidationError(
                        "Home team has already won the game"
                    )
                if (
                    game.away_team_score >= sport.win_points_threshold
                    and (game.away_team_score - game.home_team_score)
                    >= sport.win_margin
                ):                    raise ValidationError(
                        "Away team has already won the game"
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Substitution(models.Model):
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="substitutions"
    )
    substitute_in = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="substitutions_in"
    )
    substitute_out = models.ForeignKey(
        "teams.Player", on_delete=models.CASCADE, related_name="substitutions_out"
    )
    period = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["game", "period"]),
            models.Index(fields=["substitute_in", "substitute_out"]),
        ]

    def clean(self):
        # Validate same team
        if self.substitute_in.team != self.substitute_out.team:
            raise ValidationError("Players must be from the same team")

        # Validate game participation
        game_teams = [self.game.home_team, self.game.away_team]
        if self.substitute_in.team not in game_teams:
            raise ValidationError("Substitute in player not in this game")

    def __str__(self):
        return f"{self.substitute_out} ↔ {self.substitute_in} (Period {self.period})"


class StartingLineup(models.Model):
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="starting_lineup"
    )
    player = models.ForeignKey("teams.Player", on_delete=models.CASCADE)
    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE)
    is_starting = models.BooleanField(default=True)

    class Meta:
        unique_together = ("game", "player")  # A player can't start multiple times

    def __str__(self):
        return f"{self.player} ({self.team}) - {'Starter' if self.is_starting else 'Bench'}"
