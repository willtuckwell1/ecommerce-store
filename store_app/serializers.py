from rest_framework import serializers

from .models import Product, Review, Store


class StoreSerializer(serializers.ModelSerializer):
    """Serialize store records for the API."""

    owner = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Store
        fields = ['id', 'name', 'description', 'owner']


class ProductSerializer(serializers.ModelSerializer):
    """Serialize product records for the API."""

    class Meta:
        model = Product
        fields = ['id', 'store', 'name', 'description', 'price', 'stock']


class ReviewSerializer(serializers.ModelSerializer):
    """Serialize review records for the API."""

    class Meta:
        model = Review
        fields = ['id', 'product', 'user', 'rating', 'comment', 'is_verified']
