"""Database models for the e-commerce application."""

from django.contrib.auth.models import User
from django.db import models


class Store(models.Model):
    """Represent a shop owned by a vendor user."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        """Return the store name for display in Django admin and templates."""
        return self.name


class Product(models.Model):
    """Represent a single product in a vendor's store."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)

    def __str__(self):
        """Return the product name for display."""
        return self.name


class Review(models.Model):
    """Capture a buyer's review for a product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(default=5)
    comment = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        """Return a readable summary for the review."""
        return f'{self.user.username} - {self.product.name}'


class Order(models.Model):
    """Record a buyer's completed checkout."""

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    total_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        """Return the order summary for display."""
        return f'Order {self.pk} for {self.user.username}'


class OrderItem(models.Model):
    """Store the quantity and price for one product in an order."""

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        """Return a compact description of the ordered quantity."""
        return f'{self.quantity} x {self.product.name}'


class ResetToken(models.Model):
    """Store password reset tokens and their expiry status."""

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=500)
    expiry_date = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def __str__(self):
        """Return a readable label for admin display."""
        return f'Reset token for {self.user.username}'
