import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0001_initial'),
    ]

    operations = [
        migrations.DeleteModel(name='Guess'),
        migrations.RemoveField(model_name='gameplayer', name='secret_number'),
        migrations.AlterUniqueTogether(name='gameplayer', unique_together=set()),
        migrations.RemoveField(model_name='gameplayer', name='turn_order'),
        migrations.AddField(
            model_name='gameplayer',
            name='character_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='gameplayer',
            name='eliminated',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='gameroom',
            name='awaiting_answer',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='gameroom',
            name='question_owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pending_questions',
                to='game.gameplayer',
            ),
        ),
        migrations.CreateModel(
            name='Accusation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('character_id', models.CharField(max_length=64)),
                ('correct', models.BooleanField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'game_player',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='accusations',
                        to='game.gameplayer',
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    'kind',
                    models.CharField(
                        choices=[
                            ('chat', 'Chat'),
                            ('question', 'Question'),
                            ('answer', 'Answer'),
                            ('system', 'System'),
                        ],
                        default='chat',
                        max_length=10,
                    ),
                ),
                ('text', models.TextField()),
                ('answer', models.CharField(blank=True, default='', max_length=3)),
                ('reply_to', models.UUIDField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'game_player',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='messages',
                        to='game.gameplayer',
                    ),
                ),
                (
                    'game_room',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='messages',
                        to='game.gameroom',
                    ),
                ),
            ],
            options={'ordering': ['created_at']},
        ),
    ]
