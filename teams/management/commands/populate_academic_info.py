from django.core.management.base import BaseCommand
from teams.models import AcademicInfo


class Command(BaseCommand):
    help = 'Populate AcademicInfo table with common year levels, courses, and sections'

    def add_arguments(self, parser):
        parser.add_argument(
            '--with-sections',
            action='store_true',
            dest='with_sections',
            help='Also create sectioned records (Section 1, Section 2...)',
        )
        parser.add_argument(
            '--sections',
            type=int,
            default=4,
            dest='sections',
            help='Number of sections to create per course (default:4)'
        )

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('Populating AcademicInfo...'))

        # Define year levels
        year_levels = [
            'Grade 11',
            'Grade 12',
            '1st Year College',
            '2nd Year College',
            '3rd Year College',
            '4th Year College',
        ]

        # Define courses for Senior High School
        shs_courses = ['STEM', 'GAS', 'HUMSS', 'ABM', 'TVL', 'Arts and Design']
        
        # Define courses for College
        college_courses = [
            'BS Computer Science',
            'BS Information Technology',
            'BS Business Administration',
            'BS Accountancy',
            'BS Psychology',
            'BS Nursing',
            'BS Education',
            'BS Engineering',
        ]

    # Define a smaller, conservative set of sections to keep generated data compact
        # Use descriptive non-letter section names (e.g. 'Section 1') instead of single letters
        sections = ['Section 1', 'Section 2', 'Section 3']

        created_count = 0
        skipped_count = 0

        # Default behavior: create only year+course entries without sections to keep the dataset small.
        # This supports the frontend flow: select year_level -> select course -> then query sections if needed.

        self.stdout.write(self.style.WARNING('\nCreating minimal year+course entries (no sections). Use --with-sections to generate sectioned records.)'))

        # Junior High (Grade 7-10) - use course='General' and section=None
        # for year in ['Grade 7', 'Grade 8', 'Grade 9', 'Grade 10']:
        #     obj, created = AcademicInfo.objects.get_or_create(
        #         year_level=year,
        #         course='General',
        #         section=None,
        #     )
        #     if created:
        #         created_count += 1
        #         self.stdout.write(f'  Created: {obj}')
        #     else:
        #         skipped_count += 1

        # Senior High (Grade 11-12) - create year+course entries without sections
        for year in ['Grade 11', 'Grade 12']:
            for course in shs_courses:
                obj, created = AcademicInfo.objects.get_or_create(
                    year_level=year,
                    course=course,
                    section=None,
                )
                if created:
                    created_count += 1
                    self.stdout.write(f'  Created: {obj}')
                else:
                    skipped_count += 1

        # College years - create year+course entries without sections
        for year in ['1st Year College', '2nd Year College', '3rd Year College', '4th Year College']:
            for course in college_courses:
                obj, created = AcademicInfo.objects.get_or_create(
                    year_level=year,
                    course=course,
                    section=None,
                )
                if created:
                    created_count += 1
                    self.stdout.write(f'  Created: {obj}')
                else:
                    skipped_count += 1

        # Optionally create sectioned entries if the user requested more detail
        with_sections = kwargs.get('with_sections', False)
        sec_count = max(1, min(10, int(kwargs.get('sections', 4))))

        if with_sections:
            # start from the smaller predefined `sections` list and extend with numbered Section X labels if needed
            if sec_count <= len(sections):
                chosen_sections = sections[:sec_count]
            else:
                extra_needed = sec_count - len(sections)
                start_idx = len(sections) + 1
                extra = [f'Section {i}' for i in range(start_idx, start_idx + extra_needed)]
                chosen_sections = sections + extra

            self.stdout.write(self.style.WARNING('\nCreating sectioned AcademicInfo entries...'))

            # Junior High sections
            # for year in ['Grade 7', 'Grade 8', 'Grade 9', 'Grade 10']:
            #     for section in chosen_sections:
            #         obj, created = AcademicInfo.objects.get_or_create(
            #             year_level=year,
            #             course='General',
            #             section=section,
            #         )
            #         if created:
            #             created_count += 1
            #             self.stdout.write(f'  Created: {obj}')
            #         else:
            #             skipped_count += 1

            # Senior High sections
            for year in ['Grade 11', 'Grade 12']:
                for course in shs_courses:
                    for section in chosen_sections:
                        obj, created = AcademicInfo.objects.get_or_create(
                            year_level=year,
                            course=course,
                            section=section,
                        )
                        if created:
                            created_count += 1
                            self.stdout.write(f'  Created: {obj}')
                        else:
                            skipped_count += 1
            # Do not generate sections for college levels by default (skip college sections)
            self.stdout.write(self.style.WARNING('\nSkipping college-level sections (no sections will be created for college years)'))

        self.stdout.write(self.style.SUCCESS(f'\n✅ Done!'))
        self.stdout.write(self.style.SUCCESS(f'  Created: {created_count} new records'))
        self.stdout.write(self.style.WARNING(f'  Skipped: {skipped_count} existing records'))
        self.stdout.write(self.style.SUCCESS(f'  Total in database: {AcademicInfo.objects.count()} records'))
