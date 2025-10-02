from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    is_active = models.BooleanField(default=True)
    pass


# Create your models here.
