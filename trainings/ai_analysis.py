from sports_management.gemini_ai import generate_response
import json

def analyze_training_data(metric_data):
    """
    Use Gemini AI to analyze training metrics and provide insights
    
    Args:
        metric_data (dict): Dictionary containing training metric data
    
    Returns:
        dict: AI-generated analysis and insights
    """
    # Format the data for AI analysis
    prompt = f"""
    As a sports training analyst, analyze this athlete's performance data and provide detailed insights:

    Metric: {metric_data['metric_name']} ({metric_data['unit']})
    Total Sessions: {metric_data['data_points_count']}
    Duration: {metric_data['duration_days']} days
    
    Performance Stats:
    - Starting Value: {metric_data['first_record']['value']}
    - Current Value: {metric_data['last_record']['value']}
    - Best Value: {metric_data['best_record']['value']}
    - Average: {metric_data['stats']['mean']}
    - Consistency (StdDev): {metric_data['consistency']['standard_deviation']}
    
    Recent Performance:
    - Recent Improvement: {metric_data['recent_improvement']['percentage']}%
    - Overall Trend: {"Positive" if metric_data['trend']['is_positive'] else "Negative" if metric_data['trend'] else "Neutral"}

    Note: {'Lower values are better' if metric_data['is_lower_better'] else 'Higher values are better'}

    Provide a comprehensive analysis including:
    1. Performance Overview
    2. Progress Assessment
    3. Consistency Analysis
    4. Recommendations for Improvement
    5. Key Achievements
    Format the response as a JSON object with these sections as keys.
    Keep each section's analysis concise but insightful (2-3 sentences per section).
    """
    
    try:
        # Get AI analysis
        ai_response = generate_response(prompt)
        # Parse JSON response
        analysis = json.loads(ai_response)
        
        # Add original metrics alongside AI analysis
        return {
            'ai_analysis': analysis,
            'metric_stats': metric_data
        }
    except Exception as e:
        return {
            'ai_analysis': {
                'Performance Overview': 'Error generating AI analysis',
                'Progress Assessment': str(e),
                'Consistency Analysis': 'Using standard statistical analysis instead',
                'Recommendations': 'Please consult with your coach for personalized recommendations',
                'Key Achievements': 'Review the statistical data below'
            },
            'metric_stats': metric_data
        }

def analyze_overall_performance(metrics_summary):
    """
    Generate overall performance analysis across all metrics
    
    Args:
        metrics_summary (list): List of metric summaries
    
    Returns:
        dict: AI-generated overall analysis
    """
    metrics_text = "\n".join([
        f"- {m['metric_name']}: {m['improvement_percentage']}% change" 
        for m in metrics_summary
    ])
    
    prompt = f"""
    As a sports performance analyst, analyze this athlete's overall progress across multiple metrics:

    Metrics Summary:
    {metrics_text}

    Total Metrics: {len(metrics_summary)}
    Improved Metrics: {sum(1 for m in metrics_summary if m['is_positive'])}

    Provide a comprehensive analysis including:
    1. Overall Progress Assessment
    2. Strengths and Areas for Improvement
    3. Training Balance Analysis
    4. Strategic Recommendations
    Format the response as a JSON object with these sections as keys.
    Keep each section's analysis concise but insightful (2-3 sentences per section).
    """
    
    try:
        # Get AI analysis
        ai_response = generate_response(prompt)
        # Parse JSON response
        analysis = json.loads(ai_response)
        
        return {
            'ai_analysis': analysis,
            'metrics_summary': metrics_summary
        }
    except Exception as e:
        return {
            'ai_analysis': {
                'Overall Progress Assessment': 'Error generating AI analysis',
                'Strengths and Areas for Improvement': str(e),
                'Training Balance Analysis': 'Using standard statistical analysis instead',
                'Strategic Recommendations': 'Please consult with your coach for personalized recommendations'
            },
            'metrics_summary': metrics_summary
        }
