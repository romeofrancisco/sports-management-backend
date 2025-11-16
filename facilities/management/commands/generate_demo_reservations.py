from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
import random
import datetime

from facilities.models import Facility, Reservation
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


class Command(BaseCommand):
    help = "Generate demo facilities and realistic past reservations"

    def add_arguments(self, parser):
        parser.add_argument('--facilities', type=int, default=3, help='Number of facilities to ensure exist')
        parser.add_argument('--reservations', type=int, default=200, help='Total number of reservations to generate')
        parser.add_argument('--days-back', type=int, default=365, help='Generate reservations within the past N days')
        parser.add_argument('--max-attempts', type=int, default=50, help='Max attempts to find a non-overlapping slot')
        parser.add_argument('--verbose', action='store_true', help='Print detailed logs about failures')
        parser.add_argument('--dry-run', action='store_true', help="Don't save reservations, just print candidate slots and reasons for rejection")
        parser.add_argument('--approval-rate', type=float, default=0.9, help='Probability a created past reservation is APPROVED (0-1)')

    def handle(self, *args, **options):
        facilities_target = options['facilities']
        reservations_target = options['reservations']
        days_back = options['days_back']
        max_attempts = options['max_attempts']

        tz = timezone.get_current_timezone()
        now = timezone.now()

        verbose = options.get('verbose', False)
        dry_run = options.get('dry_run', False)
        approval_rate = float(options.get('approval_rate', 0.9))
        # Ensure there are some facilities
        existing = list(Facility.objects.all())
        created = 0
        if len(existing) < facilities_target:
            FACILITY_BASE_NAMES = [
                'Main Gymnasium', 'Indoor Court', 'Outdoor Field', 'Tennis Complex', 'Aquatic Center',
                'Fitness Studio', 'Community Hall', 'Multipurpose Arena', 'Training Centre', 'Practice Pitch'
            ]
            LOCATIONS = [
                'Sports Complex, 12 Stadium Ave',
                'Campus Recreation, West Drive',
                'Community Center, 5 Park Lane',
                'North Campus, Building A',
                'Municipal Grounds, 88 Central Rd',
                'Athletics Park, 7 River Rd',
                'Downtown Recreation Hub, 101 Elm St'
            ]

            used_names = set([f.name for f in existing])
            for i in range(len(existing) + 1, facilities_target + 1):
                base = random.choice(FACILITY_BASE_NAMES)
                name = base
                suffix = 1
                # ensure unique name
                while name in used_names:
                    suffix += 1
                    name = f"{base} {suffix}"
                location = random.choice(LOCATIONS)
                description = random.choice([
                    'Indoor facility with hardwood court and spectator seating',
                    'Outdoor grass pitch for football and rugby',
                    'Multi-court tennis complex with floodlights',
                    'Community hall suitable for events and training sessions'
                ])
                capacity = random.choice([24, 50, 100, 250, 500])
                f = Facility.objects.create(name=name, location=location, description=description, capacity=capacity)
                existing.append(f)
                used_names.add(name)
                created += 1

        self.stdout.write(self.style.SUCCESS(f'Ensured {len(existing)} facilities (created {created})'))

        # Select coach users; try several heuristics and fall back to any active users
        coaches = list(User.objects.filter(is_active=True).filter(
            Q(coach_profile__isnull=False) | Q(role__iexact='coach') | Q(is_staff=True)
        ))
        if not coaches:
            # fallback: any active user
            coaches = list(User.objects.filter(is_active=True))

        if not coaches:
            self.stdout.write(self.style.ERROR('No users available to assign as coaches. Create users first.'))
            return

        # For reproducibility, you can set seed here if desired
        # random.seed(0)

        reservations_created = 0
        total_attempts = 0

        # Keep per-facility reservation lists to help avoid overlaps faster
        for i in range(reservations_target):
            facility = random.choice(existing)
            coach = random.choice(coaches)

            # For demo data, the coach is always the one who requested the reservation
            requested_by = coach

            # Try to find a non-overlapping slot
            attempt = 0
            success = False
            while attempt < max_attempts and not success:
                attempt += 1
                total_attempts += 1
                # pick a random day in the past range
                days_ago = random.randint(1, max(1, days_back))
                day = now - datetime.timedelta(days=days_ago)

                # pick hour between 6 and 20
                start_hour = random.randint(6, 19)
                duration_hours = random.choice([1, 1.5, 2, 2.5, 3])
                start_minute = random.choice([0, 0, 0, 15, 30, 45])

                start = datetime.datetime(year=day.year, month=day.month, day=day.day,
                                          hour=int(start_hour), minute=int(start_minute), tzinfo=tz)
                end = start + datetime.timedelta(hours=duration_hours)

                # sanity: ensure end is before now
                if end >= now:
                    continue

                # quick overlap check
                overlaps = Reservation.objects.filter(facility=facility, start_datetime__lt=end, end_datetime__gt=start)
                if overlaps.exists():
                    if verbose:
                        self.stdout.write(f'[{i+1}] Attempt {attempt}: overlap for {facility} {start} - {end} (conflicts: {overlaps.count()})')
                    continue

                # create reservation
                notes = random.choice([
                    'Team practice', 'Coach training', 'Friendly match', 'Community event', 'Maintenance',
                    'League practice', 'Open court session', 'Junior training', 'Senior match', 'University training'
                ])

                res = Reservation(facility=facility, coach=coach, requested_by=requested_by, start_datetime=start, end_datetime=end, notes=notes)
                # For past reservations, probabilistically set approved state if field exists
                try:
                    if hasattr(res, 'status'):
                        # set APPROVED with probability approval_rate, otherwise leave default
                        if random.random() <= approval_rate:
                            try:
                                res.status = 'approved'
                            except Exception:
                                pass

                    # validate (but don't save if dry-run)
                    try:
                        res.full_clean()
                    except ValidationError as ve:
                        if verbose:
                            self.stdout.write(f'[{i+1}] Attempt {attempt}: validation error: {ve.message_dict}')
                        # validation failed, try another slot
                        continue

                    if dry_run:
                        reservations_created += 1
                        success = True
                        if verbose:
                                self.stdout.write(f'[DRY RUN] Would create reservation: facility={facility.id} coach={coach.id} requested_by={requested_by.id if requested_by else None} {start} - {end} notes="{notes}"')
                    else:
                        res.save()
                        reservations_created += 1
                        success = True
                except Exception as e:
                    # unexpected error, report and continue
                    self.stderr.write(f'Error creating reservation on attempt {attempt} for facility {facility.id}: {e}')
                    if verbose:
                        import traceback
                        traceback.print_exc()
                    break

        self.stdout.write(self.style.SUCCESS(f'Created {reservations_created} reservations (attempted {total_attempts} candidate slots)'))
        if dry_run:
            self.stdout.write(self.style.WARNING('Dry run: no reservations were saved'))
