from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Sum, F, Q
from datetime import date
from sports.models import Sport
from utils.file_uploads import league_logo_upload_path


class Tournament(models.Model):
    class Division(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        PAUSED = "paused", "Paused"

    name = models.CharField(max_length=255)
    sport = models.ForeignKey("sports.Sport", on_delete=models.CASCADE, related_name="tournaments")
    division = models.CharField(
        max_length=10, choices=Division.choices, default=Division.MALE
    )
    logo = models.ImageField(upload_to=league_logo_upload_path, null=True, blank=True)
    teams = models.ManyToManyField("teams.Team", related_name="tournaments", blank=True)
    is_recorded = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPCOMING
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            models.Case(
                models.When(status="ongoing", then=0),
                models.When(status="upcoming", then=1),
                default=2,
                output_field=models.IntegerField(),
            ),
            "-start_date",
        ]
        unique_together = ["name", "sport"]

    def __str__(self):
        end_year = self.end_date.year if self.end_date else "TBD"
        return f"{self.name} Tournament {self.start_date.year} - {end_year} ({self.status})"

    def clean(self):
        """Validate tournament data"""
        # Check start/end date if both are not None
        if self.start_date and self.end_date:
            if self.start_date >= self.end_date:
                raise ValidationError("Tournament end date must be after start date")

    def validate_team_division(self, team):
        """Validate that a team's division matches the tournament's division"""
        if team.division != self.division:
            raise ValidationError(
                f"Team '{team.name}' has division '{team.division}' but tournament '{self.name}' requires '{self.division}' division."
            )

    def add_team(self, team):
        """Add a team to the tournament with division validation"""
        self.validate_team_division(team)
        self.teams.add(team)

    def remove_team(self, team):
        """Remove a team from the tournament"""
        self.teams.remove(team)

    @property
    def get_bracket(self):
        return getattr(self, "bracket", None)

    @property
    def games_count(self):
        """Return the number of games in the tournament"""
        return self.games.count()

    @property
    def games_played(self):
        """Return the number of completed games in the tournament"""
        return self.games.filter(status="completed").count()

    @property
    def avg_points_per_game(self):
        """Calculate the average points per game across all completed games in the tournament"""
        completed_games = self.games.filter(status="completed")
        if not completed_games.exists():
            return 0

        total_points = sum(
            game.home_team_score + game.away_team_score for game in completed_games
        )
        return (
            round(total_points / completed_games.count(), 2)
            if completed_games.count() > 0
            else 0
        )

    def start_tournament(self, current_date=None):
        """Start the tournament"""
        if self.status != self.Status.UPCOMING and self.status != self.Status.PAUSED:
            raise ValidationError(
                "Tournament can only start from Upcoming or Paused status"
            )

        # Use provided date for testing or date.today() by default
        today = current_date if current_date is not None else date.today()

        if self.start_date != today:
            raise ValidationError("Tournament can only start on its start date")

        self.status = self.Status.ONGOING
        self.save()

    def complete_tournament(self):
        """Complete the tournament"""
        if self.status != self.Status.ONGOING:
            raise ValidationError("Tournament can only be completed from Ongoing status")

        self.status = self.Status.COMPLETED
        self.save()

    def pause_tournament(self):
        """Pause the tournament"""
        if self.status != self.Status.ONGOING:
            raise ValidationError("Tournament can only be paused from Ongoing status")

        self.status = self.Status.PAUSED
        self.save()

    def cancel_tournament(self):
        """Cancel the tournament"""
        if self.status == self.Status.COMPLETED:
            raise ValidationError("Cannot cancel a completed tournament")

        self.status = self.Status.CANCELED
        self.save()

    def standings(self, request=None):
        """Calculate standings for all teams in the tournament"""
        from games.models import Game, GameSet
        from brackets.models import Bracket

        sport = self.sport
        scoring_type = sport.scoring_type  # "points", "sets", or "goals"
        
        # Get all completed games in this tournament
        all_games = Game.objects.filter(tournament=self, status="completed")
        teams = self.teams.all()

        # Check if tournament has a bracket and get elimination type
        bracket = self.get_bracket
        is_round_robin = bracket and bracket.elimination_type == Bracket.ELIMINATION_TYPES.ROUND_ROBIN

        standings = []

        for team in teams:
            matches_played = all_games.filter(
                Q(home_team=team) | Q(away_team=team)
            ).count()

            wins = all_games.filter(
                Q(home_team=team, home_team_score__gt=F("away_team_score"))
                | Q(away_team=team, away_team_score__gt=F("home_team_score"))
            ).count()

            losses = all_games.filter(
                Q(home_team=team, home_team_score__lt=F("away_team_score"))
                | Q(away_team=team, away_team_score__lt=F("home_team_score"))
            ).count()

            ties = 0
            if sport.has_tie:
                ties = all_games.filter(
                    Q(home_team=team, home_team_score=F("away_team_score"))
                    | Q(away_team=team, away_team_score=F("home_team_score"))
                ).count()

            # Check if team won the tournament
            is_champion = Bracket.objects.filter(
                tournament=self, winner=team
            ).exists()

            win_percentage = round(wins / matches_played, 3) if matches_played else 0.000

            # Base team data for any sport type
            team_data = {
                "team_id": team.id,
                "team_name": team.name,
                "team_slug": team.slug,
                "team_logo": (
                    request.build_absolute_uri(team.logo.url)
                    if team.logo and request
                    else None
                ),
                "is_champion": is_champion,
                "matches_played": matches_played,
                "wins": wins,
                "losses": losses,
                "win_percentage": win_percentage,
            }

            if sport.has_tie:
                team_data["ties"] = ties

            # Different calculation logic based on scoring type
            if scoring_type == "sets":
                # For set-based sports like volleyball
                sets_won = 0
                sets_lost = 0
                
                # Calculate match points (used for round robin)
                if is_round_robin:
                    points = wins * 3 + ties * 1  # Standard 3 points for win, 1 for tie
                else:
                    points = wins * 2  # Standard 2 points for match win

                # Get team games
                team_games = all_games.filter(Q(home_team=team) | Q(away_team=team))

                # Count sets won and lost by this team
                total_points_scored = 0
                total_points_conceded = 0

                for game in team_games:
                    game_sets = GameSet.objects.filter(game=game)
                    if game.home_team == team:
                        sets_won += GameSet.objects.filter(
                            game=game, winner=team
                        ).count()
                        sets_lost += GameSet.objects.filter(
                            game=game, winner=game.away_team
                        ).count()

                        # Calculate points per set
                        for game_set in game_sets:
                            total_points_scored += game_set.home_team_score
                            total_points_conceded += game_set.away_team_score
                    else:  # Away team
                        sets_won += GameSet.objects.filter(
                            game=game, winner=team
                        ).count()
                        sets_lost += GameSet.objects.filter(
                            game=game, winner=game.home_team
                        ).count()

                        # Calculate points per set
                        for game_set in game_sets:
                            total_points_scored += game_set.away_team_score
                            total_points_conceded += game_set.home_team_score

                # Calculate set ratio
                set_ratio = (
                    round(sets_won / sets_lost, 3) if sets_lost > 0 else sets_won
                )

                # Calculate Sets Win Percentage
                sets_played = sets_won + sets_lost
                sets_win_percentage = (
                    round((sets_won / sets_played) * 100, 1) if sets_played > 0 else 0
                )

                # Calculate Points Per Set
                points_per_set = (
                    round(total_points_scored / sets_played, 1)
                    if sets_played > 0
                    else 0
                )
                points_conceded_per_set = (
                    round(total_points_conceded / sets_played, 1)
                    if sets_played > 0
                    else 0
                )
                point_differential_per_set = (
                    round(
                        (total_points_scored - total_points_conceded) / sets_played, 1
                    )
                    if sets_played > 0
                    else 0
                )

                team_data.update(
                    {
                        "sets_won": sets_won,
                        "sets_lost": sets_lost,
                        "set_ratio": set_ratio,
                        "points": points,  # Match points
                        "sets_win_percentage": sets_win_percentage,
                        "points_per_set": points_per_set,
                        "points_conceded_per_set": points_conceded_per_set,
                        "point_differential_per_set": point_differential_per_set,
                    }
                )
            else:
                # For points-based sports, calculate point differential and PPG
                home_games = all_games.filter(home_team=team)
                away_games = all_games.filter(away_team=team)

                total_points_scored = 0
                total_points_conceded = 0

                for game in home_games:
                    total_points_scored += game.home_team_score
                    total_points_conceded += game.away_team_score

                for game in away_games:
                    total_points_scored += game.away_team_score
                    total_points_conceded += game.home_team_score

                # Calculate match points for round robin
                if is_round_robin:
                    match_points = wins * 3 + ties * 1
                    team_data["points"] = match_points

                # Calculate PPG and point differential
                points_per_game = (
                    round(total_points_scored / matches_played, 1)
                    if matches_played > 0
                    else 0
                )
                points_conceded_per_game = (
                    round(total_points_conceded / matches_played, 1)
                    if matches_played > 0
                    else 0
                )
                point_differential = total_points_scored - total_points_conceded
                point_differential_avg = (
                    round(point_differential / matches_played, 1)
                    if matches_played > 0
                    else 0
                )

                team_data.update(
                    {
                        "points_per_game": points_per_game,
                        "points_conceded_per_game": points_conceded_per_game,
                        "point_differential": point_differential,
                        "point_differential_avg": point_differential_avg,
                    }
                )

            standings.append(team_data)

        # Custom sorting based on bracket type and scoring type
        if is_round_robin:
            # Round Robin: Sort by points first (like seasons)
            if scoring_type == "sets":
                standings.sort(
                    key=lambda t: (
                        -t["is_champion"],
                        -t.get("points", 0),
                        -t.get("set_ratio", 0),
                        -t.get("sets_won", 0),
                    )
                )
            else:
                standings.sort(
                    key=lambda t: (
                        -t["is_champion"],
                        -t.get("points", 0),
                        -t.get("point_differential", 0),
                    )
                )
        else:
            # Elimination: Sort by win ratio
            if scoring_type == "sets":
                standings.sort(
                    key=lambda t: (
                        -t["is_champion"],
                        -t["win_percentage"],
                        -t.get("set_ratio", 0),
                        -t.get("sets_won", 0),
                    )
                )
            else:
                standings.sort(
                    key=lambda t: (
                        -t["is_champion"],
                        -t["win_percentage"],
                        -t.get("point_differential", 0),
                    )
                )

        # Add ranks
        for i, team in enumerate(standings, start=1):
            team["rank"] = i

        return standings
