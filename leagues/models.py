from django.db import models
from django.core.exceptions import ValidationError
from django.db.models import Sum, F, Q
from datetime import date
from sports.models import Sport
from utils.file_uploads import league_logo_upload_path


class League(models.Model):
    class Division(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    name = models.CharField(max_length=255)
    sport = models.ForeignKey("sports.Sport", on_delete=models.CASCADE)
    division = models.CharField(
        max_length=10, choices=Division.choices, default=Division.MALE
    )
    logo = models.ImageField(upload_to=league_logo_upload_path, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ["name", "sport"]

    def __str__(self):
        return f"{self.name} ({self.sport})"

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError("End date must be after start date")

    def standings(self, request=None):
        from games.models import Game, GameSet
        from brackets.models import Bracket

        sport = self.sport
        scoring_type = sport.scoring_type  # "points", "sets", or "goals"
        seasons = self.seasons.prefetch_related("teams", "games").all()
        all_games = Game.objects.filter(season__in=seasons, status="completed")

        teams = set()
        for season in seasons:
            teams.update(season.teams.all())

        standings = []

        for team in teams:
            team_seasons = seasons.filter(teams=team)
            seasons_participated = team_seasons.count()

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

            # Count championships (1st rank in any season)
            championships = Bracket.objects.filter(
                season__in=seasons, winner=team
            ).count()

            win_ratio = round(wins / matches_played, 3) if matches_played else 0.000

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
                "championships": championships,
                "seasons_participated": seasons_participated,
                "matches_played": matches_played,
                "wins": wins,
                "losses": losses,
                "win_ratio": win_ratio,
            }

            if sport.has_tie:
                team_data["ties"] = ties

            # Different calculation logic based on scoring type
            if scoring_type == "sets":
                # For set-based sports like volleyball, calculate:
                # 1. Sets won/lost
                # 2. Set ratio
                sets_won = 0
                sets_lost = 0
                points = wins * 2  # Standard 2 points for match win in volleyball

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

        # Custom sorting based on scoring type
        if scoring_type == "sets":
            # For set-based sports, sort by:
            # 1. Championships (highest first)
            # 2. Set ratio
            # 3. Sets won
            standings.sort(
                key=lambda t: (
                    -t["championships"],
                    -t.get("set_ratio", 0),
                    -t.get("sets_won", 0),
                )
            )
        else:
            # For point-based sports, sort by:
            # 1. Championships (highest first)
            # 2. Win ratio
            # 3. Point differential
            standings.sort(
                key=lambda t: (
                    -t["championships"],
                    -t["win_ratio"],
                    -t.get("point_differential", 0),
                )
            )

        # Only take top 10
        standings = standings[:10]

        # Add ranks to top 10
        for i, team in enumerate(standings, start=1):
            team["rank"] = i

        return standings


class Season(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        CANCELED = "canceled", "Canceled"
        PAUSED = "paused", "Paused"

    name = models.CharField(max_length=255, blank=True)
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="seasons")
    teams = models.ManyToManyField("teams.Team", related_name="leagues")
    is_recorded = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.UPCOMING
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True)

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
        unique_together = ["league", "name"]

    def __str__(self):
        end_year = self.end_date.year if self.end_date else "TBD"
        return f"{self.league.name} Season {self.start_date.year} - {end_year} ({self.status})"

    def clean(self):
        # Only one ongoing season per league
        if self.status == self.Status.ONGOING:
            ongoing = Season.objects.filter(
                league=self.league, status=self.Status.ONGOING
            )
            if self.pk:
                ongoing = ongoing.exclude(pk=self.pk)
            if ongoing.exists():
                raise ValidationError(
                    "A league can only have one ongoing season at a time."
                )
        # Only check start/end date if both are not None
        if self.start_date and self.end_date:
            if self.start_date >= self.end_date:
                raise ValidationError("Season end date must be after start date")
            if self.end_date > self.end_date:
                raise ValidationError("Season cannot end after league end date")

    def validate_team_division(self, team):
        """Validate that a team's division matches the league's division"""
        if team.division != self.league.division:
            raise ValidationError(
                f"Team '{team.name}' has division '{team.division}' but league '{self.league.name}' requires '{self.league.division}' division."
            )

    def add_team(self, team):
        """Add a team to the season with division validation"""
        self.validate_team_division(team)
        self.teams.add(team)

    def remove_team(self, team):
        """Remove a team from the season"""
        self.teams.remove(team)

    @property
    def get_bracket(self):
        return getattr(self, "bracket", None)

    @property
    def games_count(self):
        """Return the number of games in the season"""
        return self.games.count()

    @property
    def games_played(self):
        """Return the number of completed games in the season"""
        return self.games.filter(status="completed").count()

    @property
    def avg_points_per_game(self):
        """Calculate the average points per game across all completed games in the season"""
        from django.db.models import Sum, F

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

    def start_season(self, current_date=None):
        if self.status != self.Status.UPCOMING and self.status != self.Status.PAUSED:
            raise ValidationError(
                "Season can only start from Upcoming or Paused status"
            )

            # Only one ongoing season per league
        ongoing = Season.objects.filter(league=self.league, status=self.Status.ONGOING)
        if self.pk:
            ongoing = ongoing.exclude(pk=self.pk)
        if ongoing.exists():
            raise ValidationError(
                "A league can only have one ongoing season at a time."
            )

        # Use provided date for testing or date.today() by default
        today = current_date if current_date is not None else date.today()

        if self.start_date != today:
            raise ValidationError("Season can only start on its start date")

        self.status = self.Status.ONGOING
        self.save()

    def complete_season(self):
        if self.status != self.Status.ONGOING:
            raise ValidationError("Season can only be completed from Ongoing status")

        self.status = self.Status.COMPLETED
        self.save()

    def pause_season(self):
        if self.status != self.Status.ONGOING:
            raise ValidationError("Season can only be paused from Ongoing status")
        self.status = self.Status.PAUSED
        self.save()

    def cancel_season(self):
        if self.status not in [self.Status.UPCOMING, self.Status.ONGOING]:
            raise ValidationError("Only upcoming or ongoing seasons can be canceled")
        self.status = self.Status.CANCELED
        self.save()

    def standings(self, request=None):
        from games.models import Game, GameSet

        sport = self.league.sport
        scoring_type = sport.scoring_type  # "points", "sets", or "goals"
        games = self.games.filter(status="completed", season=self.id)
        standings = []

        for team in self.teams.all():
            team_games = games.filter(Q(home_team=team) | Q(away_team=team))
            matches_played = team_games.count()

            # Calculate match wins/losses
            wins = team_games.filter(
                Q(home_team=team, home_team_score__gt=F("away_team_score"))
                | Q(away_team=team, away_team_score__gt=F("home_team_score"))
            ).count()

            losses = team_games.filter(
                Q(home_team=team, home_team_score__lt=F("away_team_score"))
                | Q(away_team=team, away_team_score__lt=F("home_team_score"))
            ).count()

            ties = 0
            if sport.has_tie:
                ties = team_games.filter(
                    Q(home_team=team, home_team_score=F("away_team_score"))
                    | Q(away_team=team, away_team_score=F("home_team_score"))
                ).count()

            team_data = {
                "team_id": team.id,
                "team_name": team.name,
                "team_slug": team.slug,
                "team_logo": (
                    request.build_absolute_uri(team.logo.url)
                    if team.logo and request
                    else None
                ),
                "matches_played": matches_played,
                "wins": wins,
                "losses": losses,
            }

            if sport.has_tie:
                team_data["ties"] = ties

            # Different calculation logic based on scoring type
            if scoring_type == Sport.SCORING_TYPES.POINTS:
                points = wins * 3 + ties * 1  # Standard 3 points for win, 1 for tie
                win_percentage = (
                    round(wins / matches_played, 3) if matches_played else 0
                )

                # Calculate points per game and point differential
                home_games = team_games.filter(home_team=team)
                away_games = team_games.filter(away_team=team)

                total_points_scored = 0
                total_points_conceded = 0

                for game in home_games:
                    total_points_scored += game.home_team_score
                    total_points_conceded += game.away_team_score

                for game in away_games:
                    total_points_scored += game.away_team_score
                    total_points_conceded += game.home_team_score

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
                        "points": points,
                        "win_percentage": win_percentage,
                        "points_per_game": points_per_game,
                        "points_conceded_per_game": points_conceded_per_game,
                        "point_differential": point_differential,
                        "point_differential_avg": point_differential_avg,
                    }
                )

            elif scoring_type == Sport.SCORING_TYPES.SETS:
                # For set-based scoring (volleyball, tennis), we care about:
                # 1. Match points (typically 2 for win, 1 for loss with sets won)
                # 2. Sets won/lost
                # 3. Set ratio

                # Get sets from completed games involving this team
                sets_won = 0
                sets_lost = 0
                points = (
                    wins * 2
                )  # Standard 2 points for match win in volleyball/tennis

                # Count sets won and lost by this team
                for game in team_games:
                    if game.home_team == team:
                        sets_won += GameSet.objects.filter(
                            game=game, winner=team
                        ).count()
                        sets_lost += GameSet.objects.filter(
                            game=game, winner=game.away_team
                        ).count()
                    else:  # Away team
                        sets_won += GameSet.objects.filter(
                            game=game, winner=team
                        ).count()
                        sets_lost += GameSet.objects.filter(
                            game=game, winner=game.home_team
                        ).count()

                # Calculate set ratio
                set_ratio = (
                    round(sets_won / sets_lost, 3) if sets_lost > 0 else sets_won
                )
                win_percentage = (
                    round(wins / matches_played, 3) if matches_played else 0
                )

                # Calculate set-specific statistics
                sets_played = sets_won + sets_lost

                # Count points scored/conceded in sets
                total_points_scored = 0
                total_points_conceded = 0
                for game in team_games:
                    game_sets = GameSet.objects.filter(game=game)
                    if game.home_team == team:
                        for game_set in game_sets:
                            total_points_scored += game_set.home_team_score
                            total_points_conceded += game_set.away_team_score
                    else:  # Away team
                        for game_set in game_sets:
                            total_points_scored += game_set.away_team_score
                            total_points_conceded += game_set.home_team_score

                # Calculate averages
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
                sets_win_percentage = (
                    round((sets_won / sets_played) * 100, 1) if sets_played > 0 else 0
                )

                team_data.update(
                    {
                        "sets_won": sets_won,
                        "sets_lost": sets_lost,
                        "set_ratio": set_ratio,
                        "points": points,  # Match points, not set points
                        "win_percentage": win_percentage,
                        "sets_played": sets_played,
                        "sets_win_percentage": sets_win_percentage,
                        "points_per_set": points_per_set,
                        "points_conceded_per_set": points_conceded_per_set,
                        "point_differential_per_set": point_differential_per_set,
                        "total_points_scored": total_points_scored,
                        "total_points_conceded": total_points_conceded,
                    }
                )

            elif scoring_type == Sport.SCORING_TYPES.GOALS:
                # For goal-based sports like soccer
                home = games.filter(home_team=team).aggregate(
                    scored=Sum("home_team_score"), conceded=Sum("away_team_score")
                )
                away = games.filter(away_team=team).aggregate(
                    scored=Sum("away_team_score"), conceded=Sum("home_team_score")
                )
                scored = (home["scored"] or 0) + (away["scored"] or 0)
                conceded = (home["conceded"] or 0) + (away["conceded"] or 0)
                goal_difference = scored - conceded
                points = wins * 3 + ties * 1

                point_ratio = round(scored / conceded, 2) if conceded else scored
                team_data.update(
                    {
                        "goals_scored": scored,
                        "goals_conceded": conceded,
                        "goal_difference": goal_difference,
                        "points": points,
                        "point_ratio": point_ratio,
                    }
                )

            standings.append(team_data)

        # Custom sorting based on scoring type
        def sort_key(team):
            if scoring_type == Sport.SCORING_TYPES.POINTS:
                # Sort by points, then win percentage, then point differential
                return (
                    -team["points"],
                    -team.get("win_percentage", 0),
                    -team.get("point_differential", 0),
                )
            elif scoring_type == Sport.SCORING_TYPES.SETS:
                # Sort by match points, then set ratio, then sets won
                return (
                    -team["points"],
                    -team.get("set_ratio", 0),
                    -team.get("sets_won", 0),
                )
            elif scoring_type == Sport.SCORING_TYPES.GOALS:
                # Sort by points, then goal difference, then goals scored
                return (
                    -team["points"],
                    -team.get("goal_difference", 0),
                    -team.get("goals_scored", 0),
                )
            return (-team.get("wins", 0),)

        sorted_standings = sorted(standings, key=sort_key)

        # Add rankings to the standings
        for rank, team in enumerate(sorted_standings, start=1):
            team["rank"] = rank

        return sorted_standings
