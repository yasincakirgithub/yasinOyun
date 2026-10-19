from django.db import models


class Comment(models.Model):
    game = models.CharField(max_length=32, db_index=True)
    author_name = models.CharField(max_length=30, blank=True, default='')
    body = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.author_name or "Misafir"}: {self.body[:40]}'
