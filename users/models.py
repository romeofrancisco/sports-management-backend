from django.db import models
from django.contrib.auth.models import BaseUserManager, AbstractUser
import cloudinary.models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)

    def create_coach(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.COACH)
        extra_fields.setdefault("is_staff", False)
        return self.create_user(email, password, **extra_fields)

    def create_player(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.PLAYER)
        extra_fields.setdefault("is_staff", False)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "Admin", "Admin"
        COACH = "Coach", "Coach"
        PLAYER = "Player", "Player"

    username = None
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    profile = models.ImageField(null=True)
    role = models.CharField(choices=Role, default=Role.PLAYER, max_length=10)
    date_of_birth = models.DateField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = CustomUserManager()

    def __str__(self):
        return f"{self.get_full_name()} ({self.role})"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_coach(self):
        return self.role == self.Role.COACH

    @property
    def is_player(self):
        return self.role == self.Role.PLAYER

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
