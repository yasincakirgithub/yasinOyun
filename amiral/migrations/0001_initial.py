# Generated manually for the Amiral Battı app.

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='GamePlayer',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('player_identifier', models.CharField(max_length=100, unique=True)),
                ('ships', models.JSONField(blank=True, default=list)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('ready', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='GameRoom',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('room_code', models.CharField(max_length=10, unique=True)),
                ('status', models.CharField(choices=[('WAITING', 'Oyuncu bekleniyor'), ('PLACING', 'Gemiler yerleştiriliyor'), ('IN_PROGRESS', 'Devam ediyor'), ('FINISHED', 'Bitti'), ('ABANDONED', 'Terk edildi')], default='WAITING', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('current_turn', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='current_turn_in', to='amiral.gameplayer')),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='wins', to='amiral.gameplayer')),
            ],
        ),
        migrations.CreateModel(
            name='Shot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('row', models.IntegerField()),
                ('col', models.IntegerField()),
                ('hit', models.BooleanField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('game_room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shots', to='amiral.gameroom')),
                ('shooter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shots_fired', to='amiral.gameplayer')),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.AddField(
            model_name='gameplayer',
            name='game_room',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='players', to='amiral.gameroom'),
        ),
    ]
