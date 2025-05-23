# Trainings App Performance Tests

This directory contains performance testing scripts for the trainings app.

## Available Tests

### 1. Performance Test (`performance_test.py`)

This script compares the performance of the old and new implementations for fetching player progress data. It performs several tests to measure execution time and database query count.

#### Usage:

```bash
python manage.py shell < trainings/tests/performance_test.py
```

### 2. API Performance Test (`api_performance_test.py`)

This script tests the performance of the multi_player API endpoint under different scenarios, including:
- All players, all dates
- Latest records only
- Last 30 days
- Paginated results
- Limited data points

#### Usage:

```bash
python manage.py shell < trainings/tests/api_performance_test.py
```

## Running Tests with Custom Parameters

You can modify the parameters at the bottom of each script to customize the tests:

```python
# In api_performance_test.py
test_multi_player_performance(
    team_slug=None,    # Use first available team or specify a team
    metric_id=None,    # Use first available metric or specify a metric
    num_runs=5,        # Number of test runs per scenario
    player_limit=20,   # Limit number of players to test with
    use_cache=True     # Enable/disable caching
)
```
