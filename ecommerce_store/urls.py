"""URL configuration for the e-commerce project."""

from django.contrib import admin
from django.urls import path

from store_app import views


# Define the routes used by the buyer, vendor, and authentication flows.
urlpatterns = [
    path("reddit/", views.reddit_feed, name="reddit_feed"),
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('register/', views.register_user, name='register'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('vendor-page/', views.vendor_page, name='vendor_page'),
    path('buyer-page/', views.buyer_page, name='buyer_page'),
    path(
        'add-to-cart/<int:product_id>/',
        views.add_to_cart,
        name='add_to_cart',
    ),
    path('cart/', views.cart, name='cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('invoice/', views.invoice, name='invoice'),
    path('create-store/', views.create_store, name='create_store'),
    path('edit-store/<int:store_id>/', views.edit_store, name='edit_store'),
    path(
        'delete-store/<int:store_id>/',
        views.delete_store,
        name='delete_store',
    ),
    path('create-product/', views.create_product, name='create_product'),
    path(
        'edit-product/<int:product_id>/',
        views.edit_product,
        name='edit_product',
    ),
    path(
        'delete-product/<int:product_id>/',
        views.delete_product,
        name='delete_product',
    ),
    path('review-product/', views.review_product, name='review_product'),
    path(
        'product-review/<int:product_id>/',
        views.product_review,
        name='product_review',
    ),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path(
        'cart/update/<int:product_id>/',
        views.update_cart,
        name='update_cart',
    ),
    path(
        'cart/remove/<int:product_id>/',
        views.remove_from_cart,
        name='remove_from_cart',
    ),
    path(
        'reset-password/<str:token>/',
        views.reset_password,
        name='reset_password',
    ),
    path('api/stores/', views.api_create_store, name='api_create_store'),
    path(
        'api/vendors/<int:vendor_id>/stores/',
        views.api_get_vendor_stores,
        name='api_get_vendor_stores',
    ),
    path(
        'api/stores/<int:store_id>/products/',
        views.api_get_store_products,
        name='api_get_store_products',
    ),
    path('api/products/', views.api_add_product, name='api_add_product'),
    path(
        'api/vendor-reviews/',
        views.api_get_vendor_reviews,
        name='api_get_vendor_reviews',
    ),
]
