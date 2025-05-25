import statistics
from trainings.models import PlayerMetricRecord, TrainingMetric
from trainings.utils import calculate_normalized_improvement

class PerformanceService:
    """Service class for performance analysis and statistical calculations
    
    Note: For the special "overall" metric, this service uses the overall_improvement_percentage
    from ProgressService.calculate_overall_improvement() when available to ensure consistency 
    across the application.
    """
    
    @staticmethod
    def calculate_metric_performance_analysis(metric_data):
        """
        Calculate performance analysis for a specific metric
        
        Args:
            metric_data: Dictionary containing metric data and data points.
                Required keys:
                - data_points: List of data point dictionaries with 'date' and 'value' keys
                
                Optional keys (defaults will be used if missing):
                - metric_id: The ID of the metric (default: "unknown")
                - metric_name: The name of the metric (default: "Unknown Metric")
                - unit: The unit of measurement (default: "")
                - is_lower_better: Whether lower values are better (default: False)
            
        Returns:
            Dictionary with performance analysis details
        """
        if len(metric_data["data_points"]) < 2:
            return None
            
        # Get sorted records for analysis
        sorted_records = sorted(metric_data["data_points"], key=lambda x: x["date"])
        first_record = sorted_records[0]
        last_record = sorted_records[-1]
        
        # Handle case where is_lower_better might not be in the metric_data
        is_lower_better = metric_data.get("is_lower_better", False)  # Default to False if missing
        
        # Get the metric_id to check if it"s the special "overall" metric
        metric_id = metric_data.get("metric_id", "unknown")

        # Calculate raw difference and improvement
        raw_diff = last_record["value"] - first_record["value"]
        improvement = -raw_diff if is_lower_better else raw_diff

        # Calculate percentage improvement
        improvement_percentage = 0
        if first_record["value"] != 0:
            # For consistency with progress_service"s overall_improvement calculation,
            # use the provided percentage if this is the "overall" metric
            if metric_id == "overall" and "overall_improvement_percentage" in metric_data and metric_data["overall_improvement_percentage"] is not None:
                # For the overall metric, we should use the consistent value from ProgressService 
                # to ensure all views show the same improvement percentage
                improvement_percentage = metric_data["overall_improvement_percentage"]
                # And set improvement to match sign for consistency in is_positive flag
                improvement = 1 if improvement_percentage > 0 else -1
            else:
                # Use shared utility function for consistent normalization weight handling
                if metric_id != "overall" and metric_id != "unknown":
                    try:
                        from trainings.models import TrainingMetric
                        metric = TrainingMetric.objects.select_related('metric_unit').get(id=metric_id)
                        normalization_weight = float(metric.metric_unit.normalization_weight) if metric.metric_unit and metric.metric_unit.normalization_weight else 1.0
                        
                        # Use the shared calculation function (current, previous)
                        improvement_data = calculate_normalized_improvement(
                            last_record["value"],   # current value
                            first_record["value"],  # previous value  
                            is_lower_better,
                            normalization_weight
                        )
                        improvement_percentage = improvement_data['percentage']
                        improvement = improvement_data['raw_value']
                        
                    except (TrainingMetric.DoesNotExist, ValueError):
                        # Fallback to manual calculation without normalization
                        raw_percentage = (raw_diff / abs(first_record["value"])) * 100
                        if is_lower_better:
                            raw_percentage = -raw_percentage
                        improvement_percentage = float(raw_percentage)
                else:
                    # Manual calculation for overall/unknown metrics
                    raw_percentage = (raw_diff / abs(first_record["value"])) * 100
                    if is_lower_better:
                        raw_percentage = -raw_percentage
                    improvement_percentage = float(raw_percentage)

        # Calculate statistics
        values = [record["value"] for record in sorted_records]
        try:
            consistency = statistics.stdev(values) if len(values) > 1 else 0
            mean_value = statistics.mean(values) if values else 0
            consistency_percentage = (consistency / abs(mean_value)) * 100 if mean_value != 0 else 0
        except statistics.StatisticsError:
            consistency = 0
            consistency_percentage = 0

        # Find best and worst performances
        if is_lower_better:
            best_record = min(sorted_records, key=lambda x: x["value"])
            worst_record = max(sorted_records, key=lambda x: x["value"])
        else:
            best_record = max(sorted_records, key=lambda x: x["value"])
            worst_record = min(sorted_records, key=lambda x: x["value"])

        # Calculate recent progress (last 3 sessions or 30% of sessions)
        recent_count = max(3, int(len(sorted_records) * 0.3))
        recent_records = sorted_records[-recent_count:]
        
        if len(recent_records) >= 2:
            recent_first = recent_records[0]
            recent_last = recent_records[-1]
            recent_diff = recent_last["value"] - recent_first["value"]
            
            # Special handling for overall metric to ensure consistency
            if metric_id == "overall":
                # For overall metric, the values are already improvement percentages
                # So the difference directly represents percentage change
                recent_percentage = recent_diff
                recent_improvement = 1 if recent_percentage > 0 else -1
            else:
                # Standard calculation for regular metrics with normalization weight applied
                recent_improvement = -recent_diff if is_lower_better else recent_diff
                
                recent_percentage = 0
                if recent_first["value"] != 0:
                    raw_recent_percentage = (recent_diff / abs(recent_first["value"])) * 100
                    if is_lower_better:
                        raw_recent_percentage = -raw_recent_percentage
                    
                    # Apply normalization weight if metric exists in database
                    if metric_id != "overall" and metric_id != "unknown":
                        try:
                            from trainings.models import TrainingMetric
                            metric = TrainingMetric.objects.select_related('metric_unit').get(id=metric_id)
                            if metric.metric_unit and metric.metric_unit.normalization_weight:
                                normalization_weight = float(metric.metric_unit.normalization_weight)
                                recent_percentage = float(raw_recent_percentage) * normalization_weight
                            else:
                                recent_percentage = float(raw_recent_percentage)
                        except (TrainingMetric.DoesNotExist, ValueError):
                            # Fallback to raw percentage if metric not found or invalid weight
                            recent_percentage = float(raw_recent_percentage)
                    else:
                        recent_percentage = float(raw_recent_percentage)
        else:
            recent_improvement = 0
            recent_percentage = 0
            
        # Return comprehensive analysis
        return {
            "metric_id": metric_data.get("metric_id", "unknown"),
            "metric_name": metric_data.get("metric_name", "Unknown Metric"),
            "unit": metric_data.get("unit", ""),
            "is_lower_better": is_lower_better,
            "data_points_count": len(sorted_records),
            "first_record": {
                "date": first_record["date"],
                "value": first_record["value"]
            },
            "last_record": {
                "date": last_record["date"],
                "value": last_record["value"]
            },
            "best_record": {
                "date": best_record["date"],
                "value": best_record["value"]
            },
            "worst_record": {
                "date": worst_record["date"],
                "value": worst_record["value"]
            },
            "overall_improvement": {
                "absolute": float(improvement),
                "percentage": float(improvement_percentage),
                "is_positive": improvement > 0
            },
            "recent_improvement": {
                "absolute": float(recent_improvement),
                "percentage": float(recent_percentage),
                "is_positive": recent_improvement > 0,
                "sessions_count": len(recent_records)
            },
            "consistency": {
                "standard_deviation": float(consistency),
                "percentage": float(consistency_percentage),
                "is_consistent": consistency_percentage < 15
            },
            "stats": {
                "mean": float(statistics.mean(values)) if values else 0,
                "median": float(statistics.median(values)) if values else 0,
                "min": float(min(values)) if values else 0,
                "max": float(max(values)) if values else 0
            }
        }
