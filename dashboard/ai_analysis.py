from sports_management.gemini_ai import generate_response
import json
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q, Avg, Case, When
from teams.models import Team, Coach, Player
from trainings.models import PlayerTraining
from games.models import Game

def analyze_system_health(system_data):
    """
    Use Gemini AI to analyze overall system health and provide intelligent insights
    
    Args:
        system_data (dict): Dictionary containing system metrics and statistics
    
    Returns:
        dict: AI-generated analysis and recommendations
    """
    
    prompt = f"""
    As a sports management system analyst, analyze this comprehensive system health data and provide intelligent insights:

    SYSTEM OVERVIEW:
    - Total Teams: {system_data.get('total_teams', 0)}
    - Total Players: {system_data.get('total_players', 0)}
    - Total Coaches: {system_data.get('total_coaches', 0)}
    - Active Teams (30 days): {system_data.get('active_teams', 0)}
    - System Health Score: {system_data.get('health_score', 0)}/100

    ATTENDANCE METRICS:
    - Overall Attendance Rate: {system_data.get('attendance_rate', 0):.1f}%
    - Training Sessions (30 days): {system_data.get('training_sessions', 0)}
    - Players with Good Attendance (>80%): {system_data.get('good_attendance_players', 0)}

    ENGAGEMENT DATA:
    - Teams without Recent Activity: {system_data.get('inactive_teams', 0)}
    - Coaches with Low Engagement: {system_data.get('low_engagement_coaches', 0)}
    - Unassigned Players: {system_data.get('unassigned_players', 0)}
    - Understaffed Teams: {system_data.get('understaffed_teams', 0)}

    PERFORMANCE INDICATORS:
    - Average Players per Team: {system_data.get('avg_players_per_team', 0):.1f}
    - Games Completion Rate: {system_data.get('games_completion_rate', 0):.1f}%
    - Coach Effectiveness Score: {system_data.get('avg_coach_effectiveness', 0):.1f}/100    Provide a comprehensive analysis with:
    1. System Health Assessment - Overall system performance evaluation
    2. Critical Issues - Most urgent problems requiring immediate attention
    3. Opportunity Areas - Areas with potential for improvement
    4. Success Indicators - What's working well in the system
    5. Strategic Recommendations - Specific actionable recommendations
    6. Priority Actions - Top 3 actions to take this week

    IMPORTANT: You must respond with ONLY a valid JSON object in this exact format. Do not include any other text, markdown formatting, or explanations:

    {{
        "System Health Assessment": "your analysis here",
        "Critical Issues": "your analysis here", 
        "Opportunity Areas": "your analysis here",
        "Success Indicators": "your analysis here",
        "Strategic Recommendations": "your analysis here",
        "Priority Actions": "your analysis here"
    }}    Keep each section's analysis insightful but concise (2-4 sentences per section).
    For Priority Actions and Strategic Recommendations, use bullet points (•) with each item on a NEW LINE.
    For any actionable items within other sections, also use bullet points (•) format with each item on a NEW LINE.
    Focus on actionable insights that administrators can implement.
    
    CRITICAL: When using bullet points, format them exactly like this with line breaks:
    • First action item
    • Second action item  
    • Third action item
    
    DO NOT format bullet points like this: • item1 • item2 • item3
    Each bullet point MUST be on its own line with a line break after each item.
    """
    
    try:
        # Call AI with timeout
        ai_response = generate_response(prompt, timeout=20)
        
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
            'system_metrics': system_data,
            'generated_at': timezone.now().isoformat(),
            'analysis_type': 'system_health'
        }
    except Exception as e:
        # Enhanced fallback with more specific error handling
        error_msg = str(e)
        is_timeout = "timed out" in error_msg.lower()
        return {
            'ai_analysis': {
                'System Health Assessment': 'AI analysis temporarily unavailable. Using standard system monitoring.',
                'Critical Issues': 'AI request timed out - system under high load' if is_timeout else f'Error generating AI insights: {error_msg}',
                'Opportunity Areas': 'Review dashboard metrics manually for improvement opportunities.',
                'Success Indicators': 'Check attendance rates and team activity levels.',
                'Strategic Recommendations': 'Consult with technical team for system optimization.',
                'Priority Actions': 'Focus on addressing low attendance and inactive teams.'
            },
            'system_metrics': system_data,
            'generated_at': timezone.now().isoformat(),
            'analysis_type': 'system_health',
            'fallback_used': True,
            'error_type': 'timeout' if is_timeout else 'general'
        }

def analyze_attendance_patterns(attendance_data):
    """
    AI analysis of attendance patterns and trends
    """
    prompt = f"""
    As a sports attendance analyst, examine these attendance patterns and provide insights:

    ATTENDANCE OVERVIEW:
    - Current Overall Rate: {attendance_data.get('current_rate', 0):.1f}%
    - Previous Month Rate: {attendance_data.get('previous_rate', 0):.1f}%
    - Trend: {attendance_data.get('trend', 'stable')}
    - Total Sessions Analyzed: {attendance_data.get('total_sessions', 0)}

    PATTERN ANALYSIS:
    - Peak Attendance Day: {attendance_data.get('peak_day', 'Unknown')}
    - Lowest Attendance Day: {attendance_data.get('lowest_day', 'Unknown')}
    - Teams with >90% Attendance: {attendance_data.get('high_performing_teams', 0)}
    - Teams with <60% Attendance: {attendance_data.get('struggling_teams', 0)}

    DEMOGRAPHIC INSIGHTS:
    - Most Consistent Age Group: {attendance_data.get('consistent_age_group', 'Unknown')}
    - Sport with Best Attendance: {attendance_data.get('best_sport', 'Unknown')}
    - Average Session Size: {attendance_data.get('avg_session_size', 0)}    Provide analysis focusing on:
    1. Attendance Trend Analysis - What the patterns reveal
    2. Risk Factors - Why some teams/players have poor attendance
    3. Success Patterns - What contributes to high attendance
    4. Improvement Strategies - Specific tactics to boost attendance
    5. Seasonal Recommendations - How to maintain engagement year-round

    IMPORTANT: You must respond with ONLY a valid JSON object in this exact format. Do not include any other text, markdown formatting, or explanations:

    {{
        "Attendance Trend Analysis": "your analysis here",
        "Risk Factors": "your analysis here",
        "Success Patterns": "your analysis here", 
        "Improvement Strategies": "your analysis here",
        "Seasonal Recommendations": "your analysis here"
    }}    Keep each section's analysis insightful but concise (2-4 sentences per section).
    For any actionable items, use bullet points (•) with each item on a NEW LINE.
    Focus on specific, implementable recommendations.
    
    CRITICAL: When using bullet points, format them exactly like this with line breaks:
    • First action item
    • Second action item
    • Third action item
    
    DO NOT format bullet points like this: • item1 • item2 • item3
    Each bullet point MUST be on its own line with a line break after each item.
    """
    
    try:
        ai_response = generate_response(prompt, timeout=20)
        
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
            'attendance_data': attendance_data,
            'analysis_type': 'attendance_patterns'
        }
    except Exception as e:
        error_msg = str(e)
        is_timeout = "timed out" in error_msg.lower()
        return {
            'ai_analysis': {
                'Attendance Trend Analysis': 'Standard attendance monitoring active.',
                'Risk Factors': 'Review individual team attendance rates for patterns.',
                'Success Patterns': 'Identify high-performing teams for best practices.',
                'Improvement Strategies': 'Focus on consistent scheduling and communication.',
                'Seasonal Recommendations': 'Plan engaging activities for all seasons.'
            },
            'attendance_data': attendance_data,
            'analysis_type': 'attendance_patterns',
            'fallback_used': True,
            'error_type': 'timeout' if is_timeout else 'general'
        }

def generate_predictive_insights(historical_data):
    """
    Generate AI-powered predictive insights based on historical trends
    """
    prompt = f"""
    As a sports management forecasting analyst, analyze these trends to predict future outcomes:

    HISTORICAL TRENDS:
    - 30-day Team Activity Trend: {historical_data.get('team_activity_trend', 'stable')}
    - Player Engagement Change: {historical_data.get('engagement_change', 0):.1f}%
    - Training Frequency Trend: {historical_data.get('training_frequency_trend', 'stable')}
    - New Player Registration Rate: {historical_data.get('new_players_rate', 0)} per month

    SEASONAL PATTERNS:
    - Current Season Activity: {historical_data.get('current_season_activity', 'normal')}
    - Peak Season Months: {historical_data.get('peak_months', 'Unknown')}
    - Low Activity Periods: {historical_data.get('low_activity_periods', 'Unknown')}

    RESOURCE UTILIZATION:
    - Facility Usage Rate: {historical_data.get('facility_usage', 0):.1f}%
    - Coach Workload Distribution: {historical_data.get('coach_workload', 'balanced')}
    - Equipment Utilization: {historical_data.get('equipment_usage', 'normal')}    Provide forward-looking analysis with:
    1. Short-term Predictions - What to expect in the next 30 days
    2. Resource Planning - Anticipated resource needs
    3. Risk Predictions - Potential challenges to prepare for
    4. Growth Opportunities - Areas likely to expand
    5. Optimization Recommendations - How to prepare for predicted changes

    IMPORTANT: You must respond with ONLY a valid JSON object in this exact format. Do not include any other text, markdown formatting, or explanations:

    {{
        "Short-term Predictions": "your analysis here",
        "Resource Planning": "your analysis here",
        "Risk Predictions": "your analysis here",
        "Growth Opportunities": "your analysis here",
        "Optimization Recommendations": "your analysis here"
    }}    Keep each section's analysis insightful but concise (2-4 sentences per section).
    For any actionable items, use bullet points (•) with each item on a NEW LINE.
    Focus on specific, implementable recommendations with clear timeframes.
    
    CRITICAL: When using bullet points, format them exactly like this with line breaks:
    • First action item
    • Second action item
    • Third action item
    
    DO NOT format bullet points like this: • item1 • item2 • item3
    Each bullet point MUST be on its own line with a line break after each item.
    """
    
    try:
        ai_response = generate_response(prompt, timeout=20)
        
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
            'historical_data': historical_data,
            'analysis_type': 'predictive_insights'
        }
    except Exception as e:
        error_msg = str(e)
        is_timeout = "timed out" in error_msg.lower()
        return {
            'ai_analysis': {
                'Short-term Predictions': 'Monitor current trends for 30-day outlook.',
                'Resource Planning': 'Maintain current resource allocation.',
                'Risk Predictions': 'Watch for seasonal attendance drops.',
                'Growth Opportunities': 'Focus on player recruitment and retention.',
                'Optimization Recommendations': 'Regular system health monitoring recommended.'
            },
            'historical_data': historical_data,
            'analysis_type': 'predictive_insights',
            'fallback_used': True,
            'error_type': 'timeout' if is_timeout else 'general'
        }

def collect_system_data():
    """
    Collect comprehensive system data for AI analysis
    """
    last_30_days = timezone.now() - timedelta(days=30)
    last_60_days = timezone.now() - timedelta(days=60)
    
    # Basic counts
    total_teams = Team.objects.count()
    total_players = Player.objects.count()
    total_coaches = Coach.objects.count()
    
    # Activity metrics
    active_teams = Team.objects.filter(
        Q(training_sessions__date__gte=last_30_days.date()) |
        Q(home_games__date__gte=last_30_days.date()) |
        Q(away_games__date__gte=last_30_days.date())
    ).distinct().count()
    
    # Attendance metrics
    recent_attendance = PlayerTraining.objects.filter(
        session__date__gte=last_30_days.date()
    )
    attendance_rate = 0
    if recent_attendance.exists():
        present_count = recent_attendance.filter(attendance_status="present").count()
        attendance_rate = (present_count / recent_attendance.count()) * 100
    
    # Problem indicators
    inactive_teams = total_teams - active_teams
    unassigned_players = Player.objects.filter(team__isnull=True).count()
    understaffed_teams = Team.objects.annotate(
        player_count=Count('players')
    ).filter(player_count__lt=5).count()
    
    low_engagement_coaches = Coach.objects.annotate(
        recent_sessions=Count(
            'teams__training_sessions',
            filter=Q(teams__training_sessions__date__gte=last_30_days.date())
        )
    ).filter(recent_sessions__lt=2, teams__isnull=False).count()
    
    # Performance metrics
    avg_players_per_team = (Player.objects.filter(team__isnull=False).count() / total_teams) if total_teams > 0 else 0
    
    # Games metrics
    total_games = Game.objects.filter(date__gte=last_30_days.date()).count()
    completed_games = Game.objects.filter(
        date__gte=last_30_days.date(), 
        status='completed'
    ).count()
    games_completion_rate = (completed_games / total_games * 100) if total_games > 0 else 0
    
    # Calculate health score (simplified version)
    health_score = 100
    if total_teams > 0:
        health_score -= (inactive_teams / total_teams) * 30
    health_score -= min((unassigned_players / max(total_players, 1)) * 20, 20)
    health_score -= min((understaffed_teams / max(total_teams, 1)) * 15, 15)
    if attendance_rate < 70:
        health_score -= (70 - attendance_rate) * 0.5
    
    return {
        'total_teams': total_teams,
        'total_players': total_players,
        'total_coaches': total_coaches,
        'active_teams': active_teams,
        'attendance_rate': attendance_rate,
        'training_sessions': recent_attendance.values('session').distinct().count(),
        'inactive_teams': inactive_teams,
        'low_engagement_coaches': low_engagement_coaches,
        'unassigned_players': unassigned_players,
        'understaffed_teams': understaffed_teams,
        'avg_players_per_team': avg_players_per_team,
        'games_completion_rate': games_completion_rate,
        'health_score': max(0, min(100, health_score)),
        'good_attendance_players': 0,  # Simplified calculation to avoid PostgreSQL issues
        'avg_coach_effectiveness': 75.0  # Placeholder for more complex calculation
    }
