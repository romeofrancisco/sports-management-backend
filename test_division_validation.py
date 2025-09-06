#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sports_management.settings')
django.setup()

from leagues.models import League, Season
from teams.models import Team
from sports.models import Sport
from django.core.exceptions import ValidationError
from rest_framework import serializers

def test_division_validation():
    print("Testing league division validation...")
    
    # Get or create a sport
    sport = Sport.objects.first()
    print(f'Using sport: {sport}')
    
    # Get teams with different divisions
    male_team = Team.objects.filter(division='male').first()
    female_team = Team.objects.filter(division='female').first()
    
    if not male_team or not female_team:
        print("Need both male and female teams for testing")
        return
    
    print(f'Male team: {male_team.name} - {male_team.division}')
    print(f'Female team: {female_team.name} - {female_team.division}')
    
    # Create test leagues
    male_league, created = League.objects.get_or_create(
        name='Test Male League',
        sport=sport,
        division='male'
    )
    female_league, created = League.objects.get_or_create(
        name='Test Female League', 
        sport=sport,
        division='female'
    )
    
    print(f'Male league: {male_league.name} - {male_league.division}')
    print(f'Female league: {female_league.name} - {female_league.division}')
    
    # Test 1: Valid assignment (male team to male league)
    try:
        male_season = Season.objects.create(
            name='Test Season 1',
            league=male_league,
            start_date='2025-01-01'
        )
        male_season.add_team(male_team)
        print("✅ PASS: Male team successfully added to male league")
        male_season.delete()
    except ValidationError as e:
        print(f"❌ FAIL: Male team to male league failed: {e}")
    
    # Test 2: Invalid assignment (female team to male league)  
    try:
        male_season = Season.objects.create(
            name='Test Season 2',
            league=male_league,
            start_date='2025-01-01'
        )
        male_season.add_team(female_team)
        print("❌ FAIL: Female team was incorrectly added to male league")
        male_season.delete()
    except ValidationError as e:
        print(f"✅ PASS: Female team correctly rejected from male league: {e}")
        male_season.delete()
    
    # Test 3: Valid assignment (female team to female league)
    try:
        female_season = Season.objects.create(
            name='Test Season 3',
            league=female_league,
            start_date='2025-01-01'
        )
        female_season.add_team(female_team)
        print("✅ PASS: Female team successfully added to female league")
        female_season.delete()
    except ValidationError as e:
        print(f"❌ FAIL: Female team to female league failed: {e}")
    
    # Test 4: Invalid assignment (male team to female league)
    try:
        female_season = Season.objects.create(
            name='Test Season 4',
            league=female_league,
            start_date='2025-01-01'
        )
        female_season.add_team(male_team)
        print("❌ FAIL: Male team was incorrectly added to female league")
        female_season.delete()
    except ValidationError as e:
        print(f"✅ PASS: Male team correctly rejected from female league: {e}")
        female_season.delete()
    
    print("\nDivision validation tests completed!")

if __name__ == '__main__':
    test_division_validation()
