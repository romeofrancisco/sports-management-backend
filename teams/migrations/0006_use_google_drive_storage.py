# Generated manually for Google Drive storage

from django.db import migrations, models
import documents.google_drive_storage


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0005_change_document_storage'),
    ]

    operations = [
        # Add google_drive_id field
        migrations.AddField(
            model_name='playerregistrationdocument',
            name='google_drive_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        # Update file field to use Google Drive storage and make it optional
        migrations.AlterField(
            model_name='playerregistrationdocument',
            name='file',
            field=models.FileField(
                blank=True,
                null=True,
                storage=documents.google_drive_storage.GoogleDriveStorage(),
                upload_to='registration_documents/'
            ),
        ),
    ]
