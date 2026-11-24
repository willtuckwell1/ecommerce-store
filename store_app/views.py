"""Authentication and session logic for the e-commerce project."""
import requests
import secrets
from datetime import timedelta
from hashlib import sha1

from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, Permission, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Order, OrderItem, Product, ResetToken, Review, Store
from .serializers import ProductSerializer, ReviewSerializer, StoreSerializer
from functions.reddit import get_reddit_posts


def ensure_group_permissions():
    """Create the vendor and buyer groups with the permissions they need."""
    vendor_group, _ = Group.objects.get_or_create(name='Vendors')
    buyer_group, _ = Group.objects.get_or_create(name='Buyers')

    vendor_permissions = Permission.objects.filter(
        content_type__app_label='store_app',
        codename__in=[
            'add_store', 'change_store', 'delete_store', 'view_store',
            'add_product', 'change_product', 'delete_product', 'view_product',
        ],
    )
    buyer_permissions = Permission.objects.filter(
        content_type__app_label='store_app',
        codename__in=['view_store', 'view_product'],
    )

    vendor_group.permissions.set(vendor_permissions)
    buyer_group.permissions.set(buyer_permissions)

    return vendor_group, buyer_group


def assign_user_group(user, account_type):
    """Assign a user to the correct vendor or buyer group."""
    vendor_group, buyer_group = ensure_group_permissions()

    if account_type == 'vendor':
        user.groups.set([vendor_group])
    else:
        user.groups.set([buyer_group])

    user.refresh_from_db()
    user.save()


def refresh_user_permissions(request):
    """Refresh the request user instance after group changes."""
    request.user.refresh_from_db()
    request.user = request.user.__class__.objects.get(pk=request.user.pk)


def is_vendor_role(request):
    """Return whether the current user can access vendor features."""
    if request.user.groups.filter(name='Vendors').exists():
        return True
    if (
        request.user.has_perm('store_app.add_store')
        or request.user.has_perm('store_app.view_store')
    ):
        return True
    if request.session.get('account_type') == 'vendor':
        assign_user_group(request.user, 'vendor')
        refresh_user_permissions(request)
        return True
    if Store.objects.filter(owner=request.user).exists():
        assign_user_group(request.user, 'vendor')
        refresh_user_permissions(request)
        return True
    return False


def is_buyer_role(request):
    """Return whether the current user can access buyer features."""
    if request.user.groups.filter(name='Buyers').exists():
        return True
    if (
        request.user.has_perm('store_app.view_product')
        or request.user.has_perm('store_app.view_store')
    ):
        return True
    if request.session.get('account_type') == 'buyer':
        assign_user_group(request.user, 'buyer')
        refresh_user_permissions(request)
        return True
    return False


def home(request):
    """Redirect returning users to their dashboard or the registration page."""
    if request.user.is_authenticated:
        if request.session.get('account_type') == 'vendor':
            return redirect('vendor_page')
        return redirect('buyer_page')

    return redirect('register')


# Validate the incoming registration data before creating a new Django user.
def register_user(request):
    """Register a new buyer or vendor account with validation."""
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        account_type = request.POST.get('account_type')

        if User.objects.filter(username=username).exists():
            return render(
                request,
                'store_app/register.html',
                {
                    'error': (
                        'Username already exists. Please choose another one.'
                    ),
                },
            )

        if User.objects.filter(email=email).exists():
            return render(
                request,
                'store_app/register.html',
                {
                    'error': 'This email is already registered.',
                },
            )

        if password != confirm_password:
            return render(
                request,
                'store_app/register.html',
                {
                    'error': (
                        'Passwords do not match. Please try again.'
                    ),
                },
            )

        if (
            username
            and email
            and password
            and confirm_password
            and account_type
        ):
            try:
                validate_password(password)
            except ValidationError as error:
                return render(
                    request,
                    'store_app/register.html',
                    {
                        'error': error.messages[0],
                    },
                )

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
            assign_user_group(user, account_type)

            request.session.flush()
            request.session['account_type'] = account_type
            return redirect('login')

    return render(request, 'store_app/register.html')


# Authenticate the user with Django and keep the session account type
# consistent.
def login_user(request):
    """Authenticate a user and redirect them to the correct dashboard."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            account_type = request.session.get('account_type')
            if account_type is None:
                if user.groups.filter(name='Vendors').exists():
                    account_type = 'vendor'
                elif user.groups.filter(name='Buyers').exists():
                    account_type = 'buyer'
                elif Store.objects.filter(owner=user).exists():
                    account_type = 'vendor'
                    assign_user_group(user, 'vendor')
                else:
                    account_type = 'buyer'
                    assign_user_group(user, 'buyer')

            request.session.flush()
            request.session['account_type'] = account_type

            login(request, user)

            if account_type == 'vendor':
                return redirect('vendor_page')
            return redirect('buyer_page')

        return render(
            request,
            'store_app/login.html',
            {'error': 'Invalid username or password.'},
        )

    return render(request, 'store_app/login.html')


# Clear the current session and log the user out using Django auth.
def logout_user(request):
    """Log out the current user and reset the session state."""
    logout(request)
    return redirect('login')


# Vendor access checks are based on Django groups and permissions rather than
# session flags.
@login_required
def vendor_page(request):
    """Display the products and stores managed by the current vendor."""
    if (
        request.session.get('account_type') == 'vendor'
        and not request.user.groups.filter(name='Vendors').exists()
    ):
        assign_user_group(request.user, 'vendor')
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')

    stores = Store.objects.filter(owner=request.user)
    stores_with_products = []
    for store in stores:
        products = Product.objects.filter(store=store)
        stores_with_products.append({'store': store, 'products': products})

    return render(
        request,
        'store_app/vendor_page.html',
        {'stores_with_products': stores_with_products},
    )


# The buyer dashboard checks the buyer permission rather than the session
# account type.
@login_required
def buyer_page(request):
    """Show the buyer dashboard with stock information and controls."""
    if (
        request.session.get('account_type') == 'buyer'
        and not request.user.groups.filter(name='Buyers').exists()
    ):
        assign_user_group(request.user, 'buyer')
    if (
        request.user.groups.filter(name='Vendors').exists()
        and not is_buyer_role(request)
    ):
        return HttpResponse('Access denied. You are not a buyer.')
    if not is_buyer_role(request):
        return HttpResponse('Access denied. You are not a buyer.')

    cart = request.session.get('cart', {})
    cart_has_items = bool(cart)
    products = Product.objects.all().order_by('name')
    return render(
        request,
        'store_app/buyer_page.html',
        {'products': products, 'cart_has_items': cart_has_items},
    )


# Stores are created and tied directly to the logged-in vendor owner.
@login_required
def create_store(request):
    """Create a store for the current vendor user."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.add_store'):
        return HttpResponse('Access denied. You are not a vendor.')

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')

        if name:
            request.session['account_type'] = 'vendor'
            Store.objects.create(
                owner=request.user,
                name=name,
                description=description,
            )
            return redirect('vendor_page')

        return render(
            request,
            'store_app/create_store.html',
            {'error': 'Store name is required.'},
        )

    return render(request, 'store_app/create_store.html')


# Only the owner of a store can edit that store record.
@login_required
def edit_store(request, store_id):
    """Update a store owned by the logged-in vendor."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.change_store'):
        return HttpResponse('Access denied. You are not a vendor.')

    store = Store.objects.filter(pk=store_id, owner=request.user).first()
    if not store:
        return redirect('vendor_page')

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')

        if name:
            store.name = name
            store.description = description
            store.save()
            return redirect('vendor_page')

        return render(
            request,
            'store_app/edit_store.html',
            {'store': store, 'error': 'Store name is required.'},
        )

    return render(request, 'store_app/edit_store.html', {'store': store})


# Deleting a store removes the record only when it belongs to the logged-in
# vendor.
@login_required
def delete_store(request, store_id):
    """Delete a store only if it belongs to the current vendor."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.delete_store'):
        return HttpResponse('Access denied. You are not a vendor.')

    store = Store.objects.filter(pk=store_id, owner=request.user).first()
    if store:
        store.delete()

    return redirect('vendor_page')


# Product creation checks the selected store and verifies the vendor owns it.
@login_required
def create_product(request):
    """Create a new product for one of the vendor's stores."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.add_product'):
        return HttpResponse('Access denied. You are not a vendor.')

    stores = Store.objects.filter(owner=request.user)

    if request.method == 'POST':
        store_id = request.POST.get('store_id')
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        price = request.POST.get('price')
        stock = request.POST.get('stock')

        store = stores.filter(pk=store_id).first()
        if store and name and price and stock:
            request.session['account_type'] = 'vendor'
            Product.objects.create(
                store=store,
                name=name,
                description=description,
                price=price,
                stock=stock,
            )
            return redirect('vendor_page')

        return render(
            request,
            'store_app/create_product.html',
            {'stores': stores, 'error': 'Please complete all product fields.'},
        )

    return render(request, 'store_app/create_product.html', {'stores': stores})


# Product updates are restricted to products owned by the logged-in vendor.
@login_required
def edit_product(request, product_id):
    """Edit a product owned by the current vendor."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.change_product'):
        return HttpResponse('Access denied. You are not a vendor.')

    product = Product.objects.filter(
        pk=product_id, store__owner=request.user).first()
    if not product:
        return redirect('vendor_page')

    stores = Store.objects.filter(owner=request.user)

    if request.method == 'POST':
        store_id = request.POST.get('store_id')
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        price = request.POST.get('price')
        stock = request.POST.get('stock')

        store = stores.filter(pk=store_id).first()
        if store and name and price and stock:
            product.store = store
            product.name = name
            product.description = description
            product.price = price
            product.stock = stock
            product.save()
            return redirect('vendor_page')

        return render(
            request,
            'store_app/edit_product.html',
            {
                'product': product,
                'stores': stores,
                'error': 'Please complete all product fields.',
            },
        )

    return render(request, 'store_app/edit_product.html',
                  {'product': product, 'stores': stores})


# Product deletion is restricted to products that the current vendor owns.
@login_required
def delete_product(request, product_id):
    """Delete a product in the vendor's store."""
    if not is_vendor_role(request):
        return HttpResponse('Access denied. You are not a vendor.')
    refresh_user_permissions(request)
    if not request.user.has_perm('store_app.delete_product'):
        return HttpResponse('Access denied. You are not a vendor.')

    product = Product.objects.filter(
        pk=product_id, store__owner=request.user).first()
    if product:
        product.delete()

    return redirect('vendor_page')


def cart_summary(request):
    """Build the current cart summary and total cost from the session."""
    cart_items = request.session.get('cart', {})
    products = []
    total_cost = 0

    for product_id, quantity in cart_items.items():
        product = Product.objects.filter(pk=product_id).first()
        if product and int(quantity) > 0:
            item_total = product.price * int(quantity)
            total_cost += item_total
            products.append({
                'product': product,
                'quantity': int(quantity),
                'item_total': item_total,
            })

    return cart_items, products, total_cost


def add_to_cart(request, product_id):
    """Add one or more units of a product to the buyer's cart."""
    if not request.user.is_authenticated:
        return redirect('login')

    product = Product.objects.filter(pk=product_id).first()
    if not product:
        return redirect('buyer_page')

    cart = request.session.get('cart', {})
    product_id_str = str(product_id)

    try:
        requested_quantity = int(
            request.POST.get('quantity', request.GET.get('quantity', 1))
        )
    except ValueError:
        requested_quantity = 1

    requested_quantity = max(1, requested_quantity)
    current_quantity = int(cart.get(product_id_str, 0))
    available_quantity = max(0, product.stock - current_quantity)

    if available_quantity <= 0:
        request.session['cart_error'] = (
            f'Only {product.stock} units of {product.name} are available. '
            'Adjust your cart quantity before checking out.'
        )
        return redirect('cart')

    if requested_quantity > available_quantity:
        request.session['cart_error'] = (
            f'Only {available_quantity} more units of {product.name} '
            'can be added to your cart.'
        )
        return redirect('cart')

    cart[product_id_str] = current_quantity + requested_quantity
    request.session['cart'] = cart
    request.session.pop('cart_error', None)

    return redirect('cart')


def update_cart(request, product_id):
    """Set the cart quantity to an exact value within stock availability."""
    if not request.user.is_authenticated:
        return redirect('login')

    product = Product.objects.filter(pk=product_id).first()
    if not product:
        return redirect('cart')

    if request.method == 'POST':
        cart = request.session.get('cart', {})
        try:
            requested_quantity = int(request.POST.get('quantity', 1))
        except ValueError:
            requested_quantity = 1

        requested_quantity = max(0, requested_quantity)
        if requested_quantity == 0:
            cart.pop(str(product_id), None)
            request.session['cart'] = cart
            return redirect('cart')

        if requested_quantity > product.stock:
            request.session['cart_error'] = (
                f'Only {product.stock} units of {product.name} are available.'
            )
            return redirect('cart')

        cart[str(product_id)] = requested_quantity
        request.session['cart'] = cart
        request.session.pop('cart_error', None)

    return redirect('cart')


def remove_from_cart(request, product_id):
    """Remove a product from the buyer's cart."""
    if not request.user.is_authenticated:
        return redirect('login')

    cart = request.session.get('cart', {})
    cart.pop(str(product_id), None)
    request.session['cart'] = cart
    return redirect('cart')


def cart(request):
    """Render the cart with the current total cost and item quantities."""
    if not request.user.is_authenticated:
        return redirect('login')

    _, products, total_cost = cart_summary(request)
    return render(
        request,
        'store_app/cart.html',
        {'products': products, 'total_cost': total_cost,
         'cart_error': request.session.pop('cart_error', None)},
    )


# Checkout generates an invoice and sends it by email before clearing the cart.
def checkout(request):
    """Confirm the cart purchase and reduce stock while creating the order."""
    if not request.user.is_authenticated:
        return redirect('login')

    cart_items, products, total_cost = cart_summary(request)

    if request.method == 'POST' and 'confirm' in request.POST:
        if not products:
            return redirect('buyer_page')

        for item in products:
            product = Product.objects.filter(pk=item['product'].pk).first()
            if product is None or item['quantity'] > product.stock:
                request.session['cart_error'] = (
                    f"{item['product'].name} has only "
                    f"{product.stock if product else 0} units available."
                )
                return redirect('cart')

        invoice_data = {
            'customer': request.user.username,
            'email': request.user.email,
            'products': [
                {
                    'name': item['product'].name,
                    'quantity': item['quantity'],
                    'item_total': str(item['item_total']),
                }
                for item in products
            ],
            'total_cost': str(total_cost),
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        order = Order.objects.create(user=request.user, total_cost=total_cost)
        for item in products:
            product = item['product']
            current_stock = product.stock - item['quantity']
            product.stock = max(0, current_stock)
            product.save()

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=item['quantity'],
                price=product.price,
            )

        request.session['invoice'] = invoice_data
        request.session['cart'] = {}
        request.session['purchased_products'] = [
            str(item['product'].pk) for item in products
        ]

        send_mail(
            'Your invoice',
            (
                f'Hello {request.user.username},\n\n'
                f'Your invoice total is ${total_cost}.\n'
                'Thank you for shopping with us.'
            ),
            'no-reply@example.com',
            [request.user.email],
            fail_silently=False,
        )

        return redirect('invoice')

    return render(
        request,
        'store_app/checkout.html',
        {'products': products, 'total_cost': total_cost},
    )


# Invoice data is read back from the session and displayed to the buyer.
def invoice(request):
    """Display the invoice generated after a successful checkout."""
    if not request.user.is_authenticated:
        return redirect('login')

    invoice_data = request.session.get('invoice', {})
    return render(
        request,
        'store_app/invoice.html',
        {'invoice': invoice_data},
    )


# Reviews are saved with a verification flag based on whether the buyer
# purchased the product.
def review_product(request):
    """Save a buyer review for a product after purchase validation."""
    if not request.user.is_authenticated:
        return redirect('login')

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        comment = request.POST.get('comment')
        rating = request.POST.get('rating')

        if product_id and comment and rating:
            product = Product.objects.filter(pk=product_id).first()
            if product:
                is_verified = OrderItem.objects.filter(
                    order__user=request.user,
                    product=product,
                ).exists()
                if not is_verified:
                    purchased_products = request.session.get(
                        'purchased_products', []
                    )
                    is_verified = str(product.pk) in purchased_products

                Review.objects.create(
                    product=product,
                    user=request.user,
                    comment=comment,
                    rating=int(rating),
                    is_verified=is_verified,
                )
                return redirect('product_review', product_id=product.pk)

    return redirect('buyer_page')


# Product reviews are displayed with user comments and verification status.
def product_review(request, product_id):
    """Show the reviews for a specific product and its buyer feedback."""
    product = Product.objects.filter(pk=product_id).first()
    if not product:
        return redirect('buyer_page')

    reviews = Review.objects.filter(product=product).order_by('-created_at')
    return render(
        request,
        'store_app/product_review.html',
        {'product': product, 'reviews': reviews},
    )


# A secure token is created so the user can reset a forgotten password.
def forgot_password(request):
    """Create a reset token and email the user a secure reset link."""
    if request.method == 'POST':
        email = request.POST.get('email')
        user = User.objects.filter(email=email).first()

        if user:
            token = secrets.token_urlsafe(16)
            token_hash = sha1(token.encode()).hexdigest()
            expiry_time = timezone.now() + timedelta(minutes=30)

            ResetToken.objects.filter(user=user, is_used=False).delete()
            ResetToken.objects.create(
                user=user,
                token=token_hash,
                expiry_date=expiry_time,
            )

            reset_url = request.build_absolute_uri(
                reverse('reset_password', kwargs={'token': token})
            )
            send_mail(
                'Password reset request',
                (
                    f'Hello {user.username},\n\n'
                    'A password reset was requested for your account.\n\n'
                    f'Click this link to reset your password: {reset_url}\n\n'
                    'If you did not request this, you can ignore this email.'
                ),
                'no-reply@example.com',
                [user.email],
                fail_silently=False,
            )
            return render(
                request,
                'store_app/forgot_password.html',
                {
                    'message': (
                        'A password reset link has been sent to your email.'
                    ),
                },
            )

        return render(
            request,
            'store_app/forgot_password.html',
            {'error': 'No account was found with that email.'},
        )

    return render(request, 'store_app/forgot_password.html')


# The reset page validates the token and updates the user's password
# securely.
def reset_password(request, token):
    """Validate the reset token and allow the user to set a new password."""
    token_hash = sha1(token.encode()).hexdigest()
    reset_record = ResetToken.objects.filter(
        token=token_hash,
        is_used=False,
    ).select_related('user').first()

    if not reset_record:
        return redirect('login')

    if timezone.now() > reset_record.expiry_date:
        reset_record.delete()
        return redirect('login')

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            return render(
                request,
                'store_app/reset_password.html',
                {'error': 'Passwords do not match.'},
            )

        if not new_password:
            return render(
                request,
                'store_app/reset_password.html',
                {'error': 'Password is required.'},
            )

        try:
            validate_password(new_password)
        except ValidationError as error:
            return render(
                request,
                'store_app/reset_password.html',
                {'error': error.messages[0]},
            )

        user = reset_record.user
        user.set_password(new_password)
        user.save()
        reset_record.is_used = True
        reset_record.save(update_fields=['is_used'])
        return redirect('login')

    return render(request, 'store_app/reset_password.html')


# API endpoint to create a new store. Requires authentication and the user must
# be logged in.
"""
API endpoint to create a new store.
Requires authentication and the user must be logged in.
"""


@api_view(['POST'])
@authentication_classes([BasicAuthentication])
@permission_classes([IsAuthenticated])
def api_create_store(request):
    """Create a new store through the API for the logged-in vendor."""
    serializer = StoreSerializer(
        data=request.data,
        context={'request': request},
    )

    if serializer.is_valid():
        serializer.save(owner=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# API endpoint to add a product to a vendor-owned store.
# Requires authentication and the user must own the store.
"""
API endpoint to add a product to a vendor-owned store.
Requires authentication and the user must own the store.
"""


@api_view(['POST'])
@authentication_classes([BasicAuthentication])
@permission_classes([IsAuthenticated])
def api_add_product(request):
    """Add a new product to one of the logged-in vendor's stores."""
    store_id = request.data.get('store')
    store = Store.objects.filter(pk=store_id, owner=request.user).first()

    if not store:
        return Response(
            {'error': 'You do not own this store.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = ProductSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# API endpoint to retrieve reviews for vendor-owned products.
# Requires authentication and the user must own the products being viewed.
"""
API endpoint to retrieve reviews for vendor-owned products.
Requires authentication and the user must own the products being viewed.
"""


@api_view(['GET'])
@authentication_classes([BasicAuthentication])
@permission_classes([IsAuthenticated])
def api_get_vendor_reviews(request):
    """Return all review records for products in the vendor's stores."""
    products = Product.objects.filter(store__owner=request.user)
    reviews = Review.objects.filter(product__in=products)
    serializer = ReviewSerializer(reviews, many=True)
    return Response(serializer.data)


# API endpoint to retrieve all stores for a specific vendor.
"""
API endpoint to retrieve all stores for a specific vendor.
"""


@api_view(['GET'])
def api_get_vendor_stores(request, vendor_id):
    """Return all stores owned by the selected vendor."""
    stores = Store.objects.filter(owner_id=vendor_id)
    serializer = StoreSerializer(stores, many=True)
    return Response(serializer.data)


# API endpoint to retrieve all products in a specific store.
"""
API endpoint to retrieve all products in a specific store.
"""


@api_view(['GET'])
def api_get_store_products(request, store_id):
    """Return all products in the selected store."""
    products = Product.objects.filter(store_id=store_id)
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)

# API endpoint to fetch recent posts from a public Reddit subreddit.
def reddit_feed(request):
    """Fetch posts from the chosen subreddit and pass them to the template."""
    # Call our helper function to fetch posts.
    reddit_data = get_reddit_posts("python")

    if isinstance(reddit_data, dict):
        posts = []
        error_message = reddit_data.get(
            'error',
            'No posts available right now.',
        )
    else:
        posts = reddit_data
        error_message = ''

    # Pass the posts and any error into the template.
    return render(
        request,
        'store_app/reddit_feed.html',
        {'posts': posts, 'error_message': error_message},
    )