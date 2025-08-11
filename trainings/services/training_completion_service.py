from django.db.models import Count, Avg, Max, Min, Q, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import statistics
import json

from trainings.models import (
    PlayerMetricRecord,
    PlayerTraining,
    TrainingSession,
    TrainingMetric,
)
from trainings.services.performance_service import PerformanceService
from trainings.utils import calculate_normalized_improvement
from sports_management.gemini_ai import generate_response


class TrainingCompletionService:
    """Service for generating training completion summaries with improvements and recommendations"""

    @staticmethod
    def generate_training_summary(session, request=None):
        """
        Generate a comprehensive training summary when a session is completed

        Args:
            session: TrainingSession instance
            request: HttpRequest instance for building absolute URIs

        Returns:
            dict: Training summary with improvements, statistics, and recommendations
        """

        # Basic session information
        session_info = {
            "session_id": session.id,
            "title": session.title,
            "description": session.description,
            "date": session.date,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "duration_minutes": session.duration_minutes,
            "location": session.location,
            "status": session.status,
            "notes": session.notes,
            "team": (
                {"id": session.team.id, "name": session.team.name}
                if session.team
                else None
            ),
        }

        # Attendance summary
        attendance_summary = TrainingCompletionService._calculate_attendance_summary(
            session
        )

        # Metrics summary and improvements
        metrics_summary = TrainingCompletionService._calculate_metrics_summary(session)

        # Player improvements
        player_improvements = TrainingCompletionService._calculate_player_improvements(
            session, request
        )

        # Training recommendations
        recommendations = TrainingCompletionService._generate_recommendations(
            session, attendance_summary, metrics_summary, player_improvements
        )

        # Overall training effectiveness score
        effectiveness_score = TrainingCompletionService._calculate_effectiveness_score(
            attendance_summary, metrics_summary, player_improvements
        )

        return {
            "session_info": session_info,
            "attendance_summary": attendance_summary,
            "metrics_summary": metrics_summary,
            "player_improvements": player_improvements,
            "recommendations": recommendations,
            "effectiveness_score": effectiveness_score,
            "generated_at": timezone.now().isoformat(),
        }

    @staticmethod
    def _calculate_attendance_summary(session):
        """Calculate attendance statistics for the session"""

        attendance_stats = (
            PlayerTraining.objects.filter(session=session)
            .values("attendance_status")
            .annotate(count=Count("id"))
        )

        attendance_data = {
            "present": 0,
            "absent": 0,
            "late": 0,
            "excused": 0,
            "pending": 0,
        }
        total_players = 0

        for stat in attendance_stats:
            status = stat["attendance_status"]
            count = stat["count"]
            if status in attendance_data:
                attendance_data[status] = count
            total_players += count

        # Calculate attendance rate
        effective_attendance = attendance_data["present"] + attendance_data["late"]
        attendance_rate = (
            (effective_attendance / total_players * 100) if total_players > 0 else 0
        )

        return {
            "total_players": total_players,
            "present": attendance_data["present"],
            "late": attendance_data["late"],
            "absent": attendance_data["absent"],
            "excused": attendance_data["excused"],
            "pending": attendance_data["pending"],
            "attendance_rate": round(attendance_rate, 1),
            "effective_attendance": effective_attendance,
        }

    @staticmethod
    def _calculate_metrics_summary(session):
        """Calculate metrics recording statistics and improvements"""

        # Get all metric records for this session
        metric_records = PlayerMetricRecord.objects.filter(
            player_training__session=session, value__isnull=False
        ).select_related("metric", "metric__metric_unit", "player_training__player")

        if not metric_records.exists():
            return {
                "total_metrics_recorded": 0,
                "unique_metrics": 0,
                "players_with_metrics": 0,
                "metrics_breakdown": [],
                "completion_rate": 0,
            }
        # Calculate basic statistics
        total_records = metric_records.count()
        unique_metrics = metric_records.values("metric").distinct().count()
        players_with_metrics = (
            metric_records.values("player_training__player").distinct().count()
        )

        # Get metrics breakdown
        metrics_breakdown = metric_records.values(
            "metric__id",
            "metric__name",
            "metric__metric_unit__code",
            "metric__is_lower_better",
        ).annotate(
            records_count=Count("id"),
            avg_value=Avg("value"),
            min_value=Min("value"),
            max_value=Max("value"),
            unique_players=Count("player_training__player", distinct=True),
        )  # Calculate expected records more accurately by counting actual assigned metrics
        # Only count players who were present or late (could reasonably record metrics)
        participating_players = PlayerTraining.objects.filter(
            session=session, attendance_status__in=["present", "late"]
        )

        # Calculate expected records based on actual assignments
        expected_records = 0
        for player_training in participating_players:
            # Get assigned metrics for this specific player
            player_assigned_metrics = player_training.assigned_metrics.count()

            # If no specific assignments, use session-level metrics
            if player_assigned_metrics == 0:
                player_assigned_metrics = session.metrics.count()

            # If still no metrics, use the unique metrics that have records
            if player_assigned_metrics == 0:
                player_assigned_metrics = unique_metrics

            expected_records += player_assigned_metrics

        # Calculate completion rate based on unique player-metric combinations to avoid >100%
        # Count unique player-metric combinations that were actually recorded
        unique_combinations_recorded = (
            metric_records.values("player_training__player", "metric")
            .distinct()
            .count()
        )

        completion_rate = (
            (unique_combinations_recorded / expected_records * 100)
            if expected_records > 0
            else 0
        )

        return {
            "total_metrics_recorded": total_records,
            "unique_metrics": unique_metrics,
            "players_with_metrics": players_with_metrics,
            "metrics_breakdown": list(metrics_breakdown),
            "completion_rate": round(completion_rate, 1),
            "expected_records": expected_records,
        }

    @staticmethod
    def _calculate_player_improvements(session, request=None):
        """Calculate individual player improvements during this session"""

        improvements = []

        # Get ALL players who participated in this session (regardless of metric records)
        all_players = PlayerTraining.objects.filter(session=session).select_related(
            "player"
        )

        for player_training in all_players:
            player = player_training.player

            # Build profile URL with request context
            profile_url = None
            if player.user.profile:
                if request:
                    profile_url = request.build_absolute_uri(player.user.profile.url)
                else:
                    profile_url = player.user.profile.url

            player_improvements = {
                "player_id": player.user.id,
                "player_name": f"{player.user.first_name} {player.user.last_name}",
                "player_profile": profile_url,
                "metrics_recorded": 0,
                "metric_improvements": [],
                "overall_improvement_percentage": 0,
                "attendance_status": player_training.attendance_status,
                "notes": player_training.notes,
            }

            # Get current session metrics for this player
            current_records = PlayerMetricRecord.objects.filter(
                player_training=player_training, value__isnull=False
            ).select_related("metric")

            total_improvement_percentage = 0
            improvement_count = 0

            for current_record in current_records:
                # Find previous record for the same metric
                previous_record = (
                    PlayerMetricRecord.objects.filter(
                        player_training__player=player,
                        metric=current_record.metric,
                        player_training__session__date__lt=session.date,
                        value__isnull=False,
                    )
                    .order_by("-player_training__session__date")
                    .first()
                )

                metric_improvement = {
                    "metric_id": current_record.metric.id,
                    "metric_name": current_record.metric.name,
                    "current_value": float(current_record.value),
                    "unit": (
                        current_record.metric.metric_unit.code
                        if current_record.metric.metric_unit
                        else ""
                    ),
                    "is_lower_better": current_record.metric.is_lower_better,
                    "has_previous_record": previous_record is not None,
                    "notes": current_record.notes,
                }

                if previous_record:
                    # Calculate improvement using the shared utility function
                    normalization_weight = 1.0
                    if (
                        current_record.metric.metric_unit
                        and current_record.metric.metric_unit.normalization_weight
                    ):
                        normalization_weight = float(
                            current_record.metric.metric_unit.normalization_weight
                        )

                    improvement_data = calculate_normalized_improvement(
                        float(current_record.value),
                        float(previous_record.value),
                        current_record.metric.is_lower_better,
                        normalization_weight,
                    )

                    metric_improvement.update(
                        {
                            "previous_value": float(previous_record.value),
                            "raw_difference": improvement_data["raw_value"],
                            "improvement_percentage": improvement_data["percentage"],
                            "is_improvement": improvement_data["percentage"] > 0,
                            "previous_session_date": previous_record.player_training.session.date,
                        }
                    )

                    total_improvement_percentage += improvement_data["percentage"]
                    improvement_count += 1
                else:
                    metric_improvement.update(
                        {
                            "previous_value": None,
                            "raw_difference": None,
                            "improvement_percentage": None,
                            "is_improvement": None,
                            "previous_session_date": None,
                            "note": "First time recording this metric",
                        }
                    )

                player_improvements["metric_improvements"].append(metric_improvement)

            player_improvements["metrics_recorded"] = len(
                player_improvements["metric_improvements"]
            )

            # Calculate overall improvement percentage for this player
            if improvement_count > 0:
                player_improvements["overall_improvement_percentage"] = round(
                    total_improvement_percentage / improvement_count, 2
                )

            improvements.append(player_improvements)

        # Sort players by overall improvement
        improvements.sort(
            key=lambda x: (
                x["overall_improvement_percentage"]
                if x["overall_improvement_percentage"]
                else -999
            ),
            reverse=True,
        )

        return improvements    
    
    @staticmethod
    def _generate_recommendations(
        session, attendance_summary, metrics_summary, player_improvements
    ):
        """Generate comprehensive training recommendations based on session data"""

        recommendations = {
            "Training Performance Analysis": [],
            "Player Development Insights": [],
            "Team Dynamics Assessment": [],
            "Training Optimization": [],
            "Strategic Recommendations": [],
            "Coach Focus Areas": [],
        }

        # Enhanced Attendance Analysis
        attendance_rate = attendance_summary["attendance_rate"]
        total_players = attendance_summary["total_players"]
        absent_count = attendance_summary["absent"]
        late_count = attendance_summary["late"]
        excused_count = attendance_summary["excused"]
        
        # Calculate key metrics for analysis
        completion_rate = metrics_summary["completion_rate"]
        unique_metrics = metrics_summary["unique_metrics"]
        players_with_metrics = metrics_summary["players_with_metrics"]
        
        # Analyze player performance patterns
        improving_players = [p for p in player_improvements if p["overall_improvement_percentage"] > 0] if player_improvements else []
        declining_players = [p for p in player_improvements if p["overall_improvement_percentage"] < -3] if player_improvements else []
        total_with_metrics = len([p for p in player_improvements if p["metrics_recorded"] > 0]) if player_improvements else 0

        # Training Performance Analysis
        performance_insights = []
        if attendance_rate >= 85:
            performance_insights.append("Excellent attendance rate demonstrates strong team commitment and engagement.")
        elif attendance_rate >= 70:
            performance_insights.append("Good attendance rate with room for improvement to maximize team development.")
        else:
            performance_insights.append("Low attendance rate requires immediate attention to maintain training effectiveness.")
            
        if completion_rate >= 80:
            performance_insights.append("Strong metrics completion rate enables comprehensive performance tracking.")
        elif completion_rate >= 60:
            performance_insights.append("Moderate metrics completion allows for basic performance analysis.")
        else:
            performance_insights.append("Low metrics completion limits ability to assess player progress effectively.")
            
        performance_insights.append(f"Training session tracked {unique_metrics} different performance metrics across {players_with_metrics} active participants.")
        
        recommendations["Training Performance Analysis"].append({
            "priority": "high" if attendance_rate < 70 or completion_rate < 60 else "medium",
            "category": "performance_overview",
            "title": "Session Performance Summary",
            "message": " ".join(performance_insights),
            "suggestion": "Continue monitoring key performance indicators and adjust training protocols based on attendance and completion patterns.",
            "impact": "Foundation for all training effectiveness and player development",
            "action_required": attendance_rate < 70 or completion_rate < 60
        })

        # Player Development Insights
        if player_improvements:
            development_analysis = []
            if len(improving_players) > total_with_metrics * 0.7:
                development_analysis.append(f"Outstanding player development with {len(improving_players)} out of {total_with_metrics} players showing improvement.")
                development_analysis.append("Current training methods are highly effective and should be maintained.")
            elif len(improving_players) > total_with_metrics * 0.5:
                development_analysis.append(f"Solid player progress with {len(improving_players)} players improving.")
                development_analysis.append("Continue current approach while providing additional support to remaining players.")
            else:
                development_analysis.append(f"Limited improvement observed with only {len(improving_players)} players progressing.")
                development_analysis.append("Review training methods and consider individualized approaches.")
                
            if declining_players:
                avg_decline = sum(p["overall_improvement_percentage"] for p in declining_players) / len(declining_players)
                development_analysis.append(f"Attention needed for {len(declining_players)} players showing performance decline (avg. {avg_decline:.1f}% decrease).")
            
            recommendations["Player Development Insights"].append({
                "priority": "high" if len(declining_players) > total_with_metrics * 0.3 else "medium",
                "category": "player_progress",
                "title": "Individual Player Development Analysis",
                "message": " ".join(development_analysis),
                "suggestion": "• Maintain successful training methods for improving players\n• Provide individual assessments for declining players\n• Consider personalized training plans for consistent improvement",
                "impact": "Direct influence on individual player growth and team performance",
                "action_required": len(declining_players) > 0
            })

        # Team Dynamics Assessment
        team_dynamics = []
        if late_count > 0:
            late_percentage = (late_count / total_players) * 100
            if late_percentage > 20:
                team_dynamics.append(f"Punctuality concerns with {late_count} players ({late_percentage:.1f}%) arriving late.")
            else:
                team_dynamics.append(f"Minor punctuality issues with {late_count} late arrivals managed effectively.")
        else:
            team_dynamics.append("Excellent punctuality with all attending players arriving on time.")
            
        if absent_count > 0:
            absence_rate = (absent_count / total_players) * 100
            if absence_rate > 30:
                team_dynamics.append("High absence rate may indicate scheduling conflicts or motivation issues.")
            else:
                team_dynamics.append(f"Manageable absence rate with {absent_count} players unable to attend.")
        
        participation_quality = "high" if completion_rate > 75 else "moderate" if completion_rate > 50 else "low"
        team_dynamics.append(f"Team engagement level assessed as {participation_quality} based on metrics participation.")
        
        recommendations["Team Dynamics Assessment"].append({
            "priority": "medium" if late_count > total_players * 0.2 else "low",
            "category": "team_cohesion",
            "title": "Team Participation and Engagement",
            "message": " ".join(team_dynamics),
            "suggestion": "• Address punctuality through earlier reminders and transportation support\n• Investigate absence patterns for potential systematic issues\n• Maintain engagement through varied training activities",
            "impact": "Team cohesion, training flow, and collective development",
            "action_required": late_count > total_players * 0.2 or absent_count > total_players * 0.3
        })

        # Training Optimization
        optimization_notes = []
        duration = session.duration_minutes
        if duration:
            if duration > 180:
                optimization_notes.append(f"Extended session duration ({duration//60}h {duration%60}m) may lead to fatigue and reduced effectiveness.")
                optimization_notes.append("Consider splitting into shorter, more focused sessions.")
            elif duration > 150:
                optimization_notes.append(f"Long training session ({duration//60}h {duration%60}m) requires careful fatigue management.")
            else:
                optimization_notes.append(f"Optimal session duration ({duration} minutes) supports focused training.")
                
        if unique_metrics > 10:
            optimization_notes.append(f"High number of tracked metrics ({unique_metrics}) may overwhelm data collection.")
            optimization_notes.append("Consider focusing on 5-7 key performance indicators per session.")
        elif unique_metrics > 0:
            optimization_notes.append(f"Appropriate metric tracking ({unique_metrics} metrics) enables effective monitoring.")
            
        recommendations["Training Optimization"].append({
            "priority": "high" if duration and duration > 180 else "medium",
            "category": "session_structure",
            "title": "Session Structure and Efficiency",
            "message": " ".join(optimization_notes) if optimization_notes else "Session structure appears well-optimized for training objectives.",
            "suggestion": "• Monitor player energy levels throughout extended sessions\n• Implement regular rest periods for sessions over 2 hours\n• Prioritize most important metrics to reduce data collection burden",
            "impact": "Training effectiveness, player fatigue management, and data quality",
            "action_required": duration and duration > 180
        })

        # Strategic Recommendations
        strategic_insights = []
        effectiveness_score = TrainingCompletionService._calculate_effectiveness_score(attendance_summary, metrics_summary, player_improvements)
        
        if effectiveness_score["score"] >= 85:
            strategic_insights.append("Excellent training effectiveness indicates optimal training protocols.")
            strategic_insights.append("Document and replicate successful strategies for consistent results.")
        elif effectiveness_score["score"] >= 65:
            strategic_insights.append("Good training effectiveness with opportunities for enhancement.")
            strategic_insights.append("Focus on improving weaker areas while maintaining strengths.")
        else:
            strategic_insights.append("Training effectiveness requires significant improvement.")
            strategic_insights.append("Comprehensive review of training methods and player engagement needed.")
            
        if metrics_summary["metrics_breakdown"]:
            well_recorded = [m for m in metrics_summary["metrics_breakdown"] if m["unique_players"] / players_with_metrics >= 0.8]
            if well_recorded:
                strategic_insights.append(f"Successfully recorded metrics ({len(well_recorded)} metrics) can serve as templates for improvement.")
                
        recommendations["Strategic Recommendations"].append({
            "priority": "high" if effectiveness_score["score"] < 65 else "medium",
            "category": "long_term_planning",
            "title": "Long-term Development Strategy",
            "message": " ".join(strategic_insights),
            "suggestion": "• Establish consistent training schedules and protocols\n• Implement regular progress reviews and strategy adjustments\n• Share successful methods across coaching staff\n• Set measurable improvement targets for next sessions",
            "impact": "Long-term team development and sustainable performance improvement",
            "action_required": effectiveness_score["score"] < 65
        })

        # Coach Focus Areas
        priority_areas = []
        if attendance_rate < 75:
            priority_areas.append("Attendance improvement through enhanced communication and motivation strategies.")
        if completion_rate < 70:
            priority_areas.append("Metrics collection process streamlining for better data capture.")
        if declining_players:
            priority_areas.append(f"Individual attention for {len(declining_players)} players showing performance decline.")
        if not priority_areas:
            priority_areas.append("Maintain current successful training approaches and continue monitoring progress.")
            
        focus_suggestions = []
        if len(improving_players) > 0:
            focus_suggestions.append("Recognize and reinforce successful player improvements to maintain momentum.")
        if total_with_metrics < total_players * 0.8:
            focus_suggestions.append("Increase player engagement in metrics recording for comprehensive tracking.")
        focus_suggestions.append("Regular one-on-one discussions with players to understand individual needs and challenges.")
        
        recommendations["Coach Focus Areas"].append({
            "priority": "critical" if attendance_rate < 60 or len(declining_players) > total_with_metrics * 0.4 else "high",
            "category": "coaching_priorities",
            "title": "Immediate Coaching Priorities",
            "message": " ".join(priority_areas),
            "suggestion": "• " + "\n• ".join(focus_suggestions),
            "impact": "Direct coaching effectiveness and player development outcomes",
            "action_required": True
        })

        return recommendations

    @staticmethod
    def _calculate_effectiveness_score(
        attendance_summary, metrics_summary, player_improvements
    ):
        """Calculate an overall training effectiveness score (0-100)"""

        # Attendance component (30% weight)
        attendance_score = min(100, attendance_summary["attendance_rate"])

        # Metrics completion component (25% weight)
        metrics_score = min(100, metrics_summary["completion_rate"])
        # Player improvement component (35% weight)
        improvement_score = 0
        if player_improvements:
            positive_improvements = [
                p
                for p in player_improvements
                if p["overall_improvement_percentage"]
                and p["overall_improvement_percentage"] > 0
            ]
            improvement_rate = len(positive_improvements) / len(player_improvements)
            improvement_score = improvement_rate * 100

        # Engagement quality component (10% weight) - measures depth of participation
        engagement_score = 0
        if attendance_summary["total_players"] > 0:
            # Calculate based on metrics per player ratio
            if metrics_summary["players_with_metrics"] > 0:
                avg_metrics_per_player = (
                    metrics_summary["total_metrics_recorded"]
                    / metrics_summary["players_with_metrics"]
                )
                # Normalize to 0-100 scale (assuming 3+ metrics per player is excellent)
                engagement_score = min(100, (avg_metrics_per_player / 3.0) * 100)

        # Calculate weighted score
        effectiveness_score = (
            attendance_score * 0.30
            + metrics_score * 0.25
            + improvement_score * 0.35
            + engagement_score * 0.10
        )

        # Determine effectiveness level
        if effectiveness_score >= 85:
            level = "excellent"
        elif effectiveness_score >= 75:
            level = "very_good"
        elif effectiveness_score >= 65:
            level = "good"
        elif effectiveness_score >= 50:
            level = "fair"
        else:
            level = "needs_improvement"
        return {
            "score": round(effectiveness_score, 1),
            "level": level,
            "components": {
                "attendance": round(attendance_score, 1),
                "metrics_completion": round(metrics_score, 1),
                "player_improvement": round(improvement_score, 1),
                "engagement": round(engagement_score, 1),
            },
        }

    @staticmethod
    def _generate_ai_insights(session, attendance_summary, metrics_summary, player_improvements, effectiveness_score):
        """
        Generate AI-powered insights and analysis for training session performance
        """
        
        # Prepare data for AI analysis
        session_data = {
            "session_title": session.title,
            "team_name": session.team.name if session.team else "No team",
            "duration_minutes": session.duration_minutes,
            "location": session.location,
            "date": session.date.strftime("%Y-%m-%d"),
            "total_players": attendance_summary["total_players"],
            "attendance_rate": attendance_summary["attendance_rate"],
            "present_players": attendance_summary["present"],
            "absent_players": attendance_summary["absent"],
            "late_players": attendance_summary["late"],
            "metrics_completion_rate": metrics_summary["completion_rate"],
            "total_metrics_recorded": metrics_summary["total_metrics_recorded"],
            "unique_metrics_tracked": metrics_summary["unique_metrics"],
            "effectiveness_score": effectiveness_score["score"],
            "effectiveness_level": effectiveness_score["level"]
        }
        
        # Analyze player improvements
        improving_players = [p for p in player_improvements if p["overall_improvement_percentage"] > 0]
        declining_players = [p for p in player_improvements if p["overall_improvement_percentage"] < -2]
        top_performer = max(player_improvements, key=lambda x: x["overall_improvement_percentage"]) if player_improvements else None
        
        player_analysis = {
            "total_players_with_data": len([p for p in player_improvements if p["metrics_recorded"] > 0]),
            "improving_players_count": len(improving_players),
            "declining_players_count": len(declining_players),
            "average_improvement": sum(p["overall_improvement_percentage"] for p in player_improvements) / len(player_improvements) if player_improvements else 0,
            "top_performer": {
                "name": top_performer["player_name"],
                "improvement": top_performer["overall_improvement_percentage"]
            } if top_performer and top_performer["overall_improvement_percentage"] > 0 else None,
            "players_needing_attention": [
                {"name": p["player_name"], "decline": p["overall_improvement_percentage"]}
                for p in declining_players[:3]  # Top 3 players needing attention
            ]
        }
        
        # Get metrics breakdown for analysis
        metrics_breakdown = metrics_summary.get("metrics_breakdown", [])
        metric_insights = []
        # Calculate total players who could record metrics (present + late)
        eligible_players = attendance_summary["present"] + attendance_summary["late"]
        
        for metric in metrics_breakdown[:5]:  # Top 5 metrics
            metric_insights.append({
                "name": metric["metric__name"],
                "records_count": metric["records_count"],
                "avg_value": round(float(metric["avg_value"]), 2) if metric["avg_value"] else 0,
                "participation_rate": round((metric["unique_players"] / eligible_players) * 100, 1) if eligible_players > 0 else 0
            })

        # Format top performer info
        top_performer_info = "None"
        if player_analysis['top_performer']:
            top_performer_info = f"{player_analysis['top_performer']['name']} ({player_analysis['top_performer']['improvement']:.1f}% improvement)"
        
        # Format metrics info
        metrics_info = "\n".join([
            f"- {m['name']}: {m['records_count']} records, avg {m['avg_value']}, {m['participation_rate']}% participation" 
            for m in metric_insights
        ]) if metric_insights else "- No metrics data available"
        
        # Format players needing attention
        attention_info = "\n".join([
            f"- {p['name']}: {p['decline']:.1f}% decline" 
            for p in player_analysis['players_needing_attention']
        ]) if player_analysis['players_needing_attention'] else "- None identified"

        prompt = f"""
        As a sports performance analyst, analyze this training session data and provide intelligent insights with actionable suggestions:

        SESSION OVERVIEW:
        - Session: {session_data['session_title']} for {session_data['team_name']}
        - Date: {session_data['date']} | Duration: {session_data['duration_minutes']} minutes
        - Location: {session_data['location']}
        - Overall Effectiveness: {session_data['effectiveness_score']}/100 ({session_data['effectiveness_level']})

        ATTENDANCE ANALYSIS:
        - Total Players: {session_data['total_players']}
        - Attendance Rate: {session_data['attendance_rate']}%
        - Present: {session_data['present_players']} | Late: {session_data['late_players']} | Absent: {session_data['absent_players']}

        PERFORMANCE DATA:
        - Metrics Completion: {session_data['metrics_completion_rate']}%
        - Total Measurements: {session_data['total_metrics_recorded']}
        - Metrics Tracked: {session_data['unique_metrics_tracked']}
        - Players with Data: {player_analysis['total_players_with_data']}

        PLAYER PERFORMANCE:
        - Players Improving: {player_analysis['improving_players_count']}
        - Players Declining: {player_analysis['declining_players_count']}
        - Average Improvement: {player_analysis['average_improvement']:.1f}%
        - Top Performer: {top_performer_info}

        KEY METRICS PERFORMANCE:
        {metrics_info}

        PLAYERS NEEDING ATTENTION:
        {attention_info}

        Provide comprehensive analysis with both insights and actionable suggestions for each category:

        1. Session Performance Analysis - Overall assessment of training effectiveness with specific improvement recommendations
        2. Player Development Insights - Individual and collective player progress patterns with development strategies
        3. Team Dynamics Assessment - How well the team performed as a unit with team building suggestions
        4. Training Optimization - Specific improvements for future sessions with implementation steps
        5. Strategic Recommendations - Long-term development strategies with measurable goals
        6. Coach Focus Areas - Priority areas for coaching attention with specific action plans

        IMPORTANT: You must respond with ONLY a valid JSON object in this exact format. Do not include any other text, markdown formatting, or explanations:

        {{
            "Session Performance Analysis": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }},
            "Player Development Insights": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }},
            "Team Dynamics Assessment": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }},
            "Training Optimization": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }},
            "Strategic Recommendations": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }},
            "Coach Focus Areas": {{
                "analysis": "your detailed analysis here (3-4 sentences)",
                "suggestions": "actionable suggestions with bullet points using • format"
            }}
        }}

        For each category, provide:
        - Analysis: 3-4 sentences of insightful analysis based on the data
        - Suggestions: Specific, actionable recommendations using bullet points (•) with each item on a NEW LINE

        CRITICAL: When using bullet points in suggestions, format them exactly like this with line breaks:
        • First specific action to take
        • Second actionable recommendation
        • Third implementation step
        
        DO NOT format bullet points like this: • item1 • item2 • item3
        Each bullet point MUST be on its own line with a line break after each item.
        Focus on specific, data-driven insights that coaches can immediately implement.
        """
        
        try:
            # Call AI with timeout
            ai_response = generate_response(prompt, timeout=25)
            
            # Check if the response is an error message
            if ai_response.startswith("Error generating response"):
                raise Exception(ai_response)
            
            # Clean the response to ensure it's valid JSON
            ai_response = ai_response.strip()
            
            # Remove any markdown formatting if present
            if ai_response.startswith('```json'):
                ai_response = ai_response.replace('```json', '').replace('```', '').strip()
            elif ai_response.startswith('```'):
                ai_response = ai_response.replace('```', '').strip()
                
            analysis = json.loads(ai_response)
            
            return {
                'ai_analysis': analysis,
                'session_data': session_data,
                'player_analysis': player_analysis,
                'metric_insights': metric_insights,
                'generated_at': timezone.now().isoformat(),
                'analysis_type': 'training_session_insights'
            }
        except Exception as e:
            # Enhanced fallback with more specific error handling
            error_msg = str(e)
            is_timeout = "timed out" in error_msg.lower()
            return {
                'ai_analysis': {
                    'Session Performance Analysis': f'Training session completed with {session_data["effectiveness_score"]}/100 effectiveness score. Standard analysis available through dashboard metrics.',
                    'Player Development Insights': f'{player_analysis["improving_players_count"]} players showed improvement while {player_analysis["declining_players_count"]} need additional support.',
                    'Team Dynamics Assessment': f'Team attendance was {session_data["attendance_rate"]}% with {session_data["metrics_completion_rate"]}% metrics completion rate.',
                    'Training Optimization': 'Focus on consistent attendance and complete metrics recording for better analysis.',
                    'Strategic Recommendations': 'Continue monitoring individual player progress and team performance trends.',
                    'Coach Focus Areas': 'Address attendance issues and ensure comprehensive performance tracking.'
                },
                'session_data': session_data,
                'player_analysis': player_analysis,
                'metric_insights': metric_insights,
                'generated_at': timezone.now().isoformat(),
                'analysis_type': 'training_session_insights',
                'fallback_used': True,
                'error_type': 'timeout' if is_timeout else 'general'
            }

    @staticmethod
    def generate_team_progress_insights(team, sessions_limit=5):
        """
        Generate AI insights for team progress over recent training sessions
        
        Args:
            team: Team instance
            sessions_limit: Number of recent sessions to analyze (default: 5)
            
        Returns:
            dict: AI-generated team progress analysis
        """
        
        # Get recent completed sessions for the team
        recent_sessions = TrainingSession.objects.filter(
            team=team,
            status=TrainingSession.Status.COMPLETED,
            date__gte=timezone.now().date() - timedelta(days=30)
        ).order_by('-date', '-start_time')[:sessions_limit]
        
        if not recent_sessions.exists():
            return {
                'ai_analysis': {
                    'Team Progress Overview': 'No recent completed training sessions found for analysis.',
                    'Performance Trends': 'Insufficient data to determine performance trends.',
                    'Player Development Patterns': 'No training data available for player development analysis.',
                    'Team Strengths': 'Cannot assess team strengths without training session data.',
                    'Areas for Improvement': 'Focus on conducting regular training sessions to enable progress tracking.',
                    'Long-term Recommendations': 'Establish consistent training schedule and performance tracking.'
                },
                'team_data': {'name': team.name, 'sessions_analyzed': 0},
                'analysis_type': 'team_progress_insights',
                'fallback_used': True,
                'error_type': 'no_data'
            }
        
        # Analyze trends across sessions
        team_metrics = {
            'sessions_analyzed': recent_sessions.count(),
            'total_training_hours': sum(s.duration_minutes for s in recent_sessions if s.duration_minutes) / 60,
            'average_attendance_rate': 0,
            'average_metrics_completion': 0,
            'total_players_trained': 0,
            'improvement_trend': 'stable'
        }
        
        session_summaries = []
        attendance_rates = []
        completion_rates = []
        
        for session in recent_sessions:
            # Calculate basic metrics for each session
            attendance = PlayerTraining.objects.filter(session=session)
            if attendance.exists():
                present_count = attendance.filter(attendance_status__in=['present', 'late']).count()
                attendance_rate = (present_count / attendance.count()) * 100
                attendance_rates.append(attendance_rate)
                
                # Metrics completion
                metric_records = PlayerMetricRecord.objects.filter(
                    player_training__session=session, 
                    value__isnull=False
                ).count()
                expected_records = attendance.filter(attendance_status__in=['present', 'late']).count() * 3  # Simplified
                completion_rate = (metric_records / max(expected_records, 1)) * 100
                completion_rates.append(min(completion_rate, 100))
                
                session_summaries.append({
                    'date': session.date.strftime('%Y-%m-%d'),
                    'title': session.title,
                    'attendance_rate': round(attendance_rate, 1),
                    'completion_rate': round(min(completion_rate, 100), 1),
                    'duration': session.duration_minutes
                })
        
        # Calculate averages
        if attendance_rates:
            team_metrics['average_attendance_rate'] = sum(attendance_rates) / len(attendance_rates)
        if completion_rates:
            team_metrics['average_metrics_completion'] = sum(completion_rates) / len(completion_rates)
        
        # Determine trend (simplified)
        if len(attendance_rates) >= 3:
            recent_avg = sum(attendance_rates[-2:]) / 2
            earlier_avg = sum(attendance_rates[:-2]) / max(len(attendance_rates) - 2, 1)
            if recent_avg > earlier_avg + 5:
                team_metrics['improvement_trend'] = 'improving'
            elif recent_avg < earlier_avg - 5:
                team_metrics['improvement_trend'] = 'declining'
        
        team_metrics['total_players_trained'] = PlayerTraining.objects.filter(
            session__in=recent_sessions
        ).values('player').distinct().count()
        
        prompt = f"""
        As a sports team development analyst, analyze this team's training progress over recent sessions:

        TEAM OVERVIEW:
        - Team: {team.name}
        - Sessions Analyzed: {team_metrics['sessions_analyzed']} (last 30 days)
        - Total Training Hours: {team_metrics['total_training_hours']:.1f}
        - Players Trained: {team_metrics['total_players_trained']}
        - Overall Trend: {team_metrics['improvement_trend']}

        PERFORMANCE METRICS:
        - Average Attendance Rate: {team_metrics['average_attendance_rate']:.1f}%
        - Average Metrics Completion: {team_metrics['average_metrics_completion']:.1f}%

        SESSION BREAKDOWN:
        {chr(10).join([f"- {s['date']}: {s['title']} | Attendance: {s['attendance_rate']}% | Metrics: {s['completion_rate']}% | Duration: {s['duration']}min" for s in session_summaries[:3]])}

        Provide comprehensive team development analysis with:
        1. Team Progress Overview - Overall assessment of team development trajectory
        2. Performance Trends - Key patterns in attendance, engagement, and metrics
        3. Player Development Patterns - How individual players are progressing as a group
        4. Team Strengths - Areas where the team excels and should continue building
        5. Areas for Improvement - Specific aspects that need attention and development
        6. Long-term Recommendations - Strategic suggestions for sustained team growth

        IMPORTANT: You must respond with ONLY a valid JSON object in this exact format. Do not include any other text, markdown formatting, or explanations:

        {{
            "Team Progress Overview": "your analysis here",
            "Performance Trends": "your analysis here",
            "Player Development Patterns": "your analysis here",
            "Team Strengths": "your analysis here",
            "Areas for Improvement": "your analysis here",
            "Long-term Recommendations": "your analysis here"
        }}

        Keep each section's analysis insightful but concise (3-5 sentences per section).
        For any actionable items, use bullet points (•) with each item on a NEW LINE.
        Focus on trends, patterns, and strategic insights for long-term team development.
        """
        
        try:
            ai_response = generate_response(prompt, timeout=25)
            
            if ai_response.startswith("Error generating response"):
                raise Exception(ai_response)
            
            ai_response = ai_response.strip()
            if ai_response.startswith('```json'):
                ai_response = ai_response.replace('```json', '').replace('```', '').strip()
            elif ai_response.startswith('```'):
                ai_response = ai_response.replace('```', '').strip()
                
            analysis = json.loads(ai_response)
            
            return {
                'ai_analysis': analysis,
                'team_data': {
                    'name': team.name,
                    'sessions_analyzed': team_metrics['sessions_analyzed'],
                    'metrics': team_metrics,
                    'recent_sessions': session_summaries
                },
                'generated_at': timezone.now().isoformat(),
                'analysis_type': 'team_progress_insights'
            }
            
        except Exception as e:
            error_msg = str(e)
            is_timeout = "timed out" in error_msg.lower()
            return {
                'ai_analysis': {
                    'Team Progress Overview': f'Team has completed {team_metrics["sessions_analyzed"]} training sessions with {team_metrics["average_attendance_rate"]:.1f}% average attendance.',
                    'Performance Trends': f'Current trend shows {team_metrics["improvement_trend"]} pattern in team performance metrics.',
                    'Player Development Patterns': f'{team_metrics["total_players_trained"]} players participated in recent training sessions.',
                    'Team Strengths': 'Review individual session reports for detailed performance insights.',
                    'Areas for Improvement': 'Focus on consistent attendance and comprehensive metrics tracking.',
                    'Long-term Recommendations': 'Maintain regular training schedule and monitor progress through detailed session analysis.'
                },
                'team_data': {
                    'name': team.name,
                    'sessions_analyzed': team_metrics['sessions_analyzed'],
                    'metrics': team_metrics,
                    'recent_sessions': session_summaries
                },
                'generated_at': timezone.now().isoformat(),
                'analysis_type': 'team_progress_insights',
                'fallback_used': True,
                'error_type': 'timeout' if is_timeout else 'general'
            }
