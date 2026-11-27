from django.db import models


class LogShippingState(models.Model):
    """How far a log file has been sent to Elasticsearch."""

    path = models.CharField(max_length=500, unique=True)
    file_id = models.CharField(max_length=64, blank=True)  # inode, changes on rotation
    offset = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "log shipping state"

    def __str__(self):
        return f"{self.path} @ {self.offset}"
