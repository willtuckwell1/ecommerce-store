"""Tests for the e-commerce store application."""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

from django.core import mail
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Order, OrderItem, Product, ResetToken, Store


class RegistrationTests(TestCase):
    """Test registration validation and account creation rules."""

    def test_register_user_rejects_mismatched_passwords(self):
        """Reject a registration when the password and confirmation do not
        match."""
        client = Client()

        response = client.post(
            '/register/',
            {
                'username': 'newbuyer',
                'email': 'newbuyer@example.com',
                'password': 'pass12345',
                'confirm_password': 'different123',
                'account_type': 'buyer',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'Passwords do not match. Please try again.',
        )
        self.assertFalse(User.objects.filter(username='newbuyer').exists())


class CartSessionTests(TestCase):
    """Exercise the cart and checkout behavior for a logged-in buyer."""

    def setUp(self):
        # Create the buyer user and product used by the cart tests.
        self.user = User.objects.create_user(
            username='buyer1',
            email='buyer1@example.com',
            password='pass123',
        )

        # Create the buyer's store and sample inventory item.
        self.store = Store.objects.create(
            name='Test Store',
            description='A test store for cart testing.',
            owner=self.user,
        )

        # Create one product to add to the cart.
        self.product = Product.objects.create(
            store=self.store,
            name='Test Product',
            description='A sample product.',
            price=Decimal('25.50'),
            stock=10,
        )

    def test_add_to_cart_adds_item_to_session(self):
        """Add a product to the cart and store the quantity in the session."""
        client = Client()
        client.force_login(self.user)

        response = client.get(f'/add-to-cart/{self.product.pk}/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.session.get('cart', {})
                         [str(self.product.pk)], 1)

    def test_cart_page_shows_products(self):
        """Display the selected cart products and their total cost."""
        client = Client()
        client.force_login(self.user)

        session = client.session
        session['cart'] = {str(self.product.pk): 2}
        session.save()

        response = client.get('/cart/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Product')
        self.assertContains(response, '51.00')

    def test_checkout_page_shows_total_and_clears_cart(self):
        """Show the checkout total before confirmation and clear the cart.
        """
        client = Client()
        client.force_login(self.user)

        session = client.session
        session['cart'] = {str(self.product.pk): 2}
        session.save()

        response = client.get('/checkout/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '51.00')

        response = client.post('/checkout/', {'confirm': 'yes'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.session.get('cart', {}), {})

    def test_add_to_cart_rejects_quantity_above_stock(self):
        """Prevent an order from adding more units than are in stock."""
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f'/add-to-cart/{self.product.pk}/',
            {'quantity': 15},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.session.get('cart', {}), {})

    def test_checkout_reduces_stock_after_purchase(self):
        """Reduce available inventory after a successful purchase."""
        client = Client()
        client.force_login(self.user)

        session = client.session
        session['cart'] = {str(self.product.pk): 2}
        session.save()

        client.post('/checkout/', {'confirm': 'yes'})

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    )
    def test_invoice_page_and_email_are_created_after_checkout(self):
        """Create an invoice and send a confirmation email after checkout."""
        client = Client()
        client.force_login(self.user)

        session = client.session
        session['cart'] = {str(self.product.pk): 2}
        session.save()

        response = client.post('/checkout/', {'confirm': 'yes'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

        invoice_response = client.get('/invoice/')

        self.assertEqual(invoice_response.status_code, 200)
        self.assertContains(invoice_response, '51.00')


class ReviewTests(TestCase):
    """Validate the buyer review and verification workflow."""

    def setUp(self):
        # Create the buyer and the product to be reviewed.
        self.user = User.objects.create_user(
            username='reviewbuyer',
            email='reviewbuyer@example.com',
            password='pass123',
        )

        # Create a store and sample product for review testing.
        self.store = Store.objects.create(
            name='Review Store',
            description='A store used for product reviews.',
            owner=self.user,
        )

        self.product = Product.objects.create(
            store=self.store,
            name='Review Product',
            description='A product used for review testing.',
            price=Decimal('15.00'),
            stock=5,
        )

    def test_review_page_can_submit_and_display_feedback(self):
        """Submit a review and ensure it is displayed on the product page."""
        client = Client()
        client.force_login(self.user)

        response = client.post(
            '/review-product/',
            {
                'product_id': self.product.pk,
                'comment': 'Great product!',
                'rating': 5,
            },
        )

        self.assertEqual(response.status_code, 302)

        review = self.product.review_set.latest('created_at')
        self.assertFalse(review.is_verified)

        review_page = client.get(f'/product-review/{self.product.pk}/')

        self.assertEqual(review_page.status_code, 200)
        self.assertContains(review_page, 'Great product!')
        self.assertContains(review_page, '5')

    def test_verified_review_after_purchase(self):
        """Mark a review as verified when the buyer has purchased the
        product."""
        client = Client()
        client.force_login(self.user)

        session = client.session
        session['purchased_products'] = [str(self.product.pk)]
        session.save()

        response = client.post(
            '/review-product/',
            {
                'product_id': self.product.pk,
                'comment': 'Verified purchase!',
                'rating': 5,
            },
        )

        self.assertEqual(response.status_code, 302)
        verified_review = self.product.review_set.get(
            comment='Verified purchase!',
        )
        self.assertTrue(
            verified_review.is_verified,
        )


class VendorStoreManagementTests(TestCase):
    """Test the vendor actions for creating and managing stores and
    products."""

    def setUp(self):
        # Create the vendor user who manages the store and products.
        self.vendor = User.objects.create_user(
            username='vendor1',
            email='vendor1@example.com',
            password='pass123',
        )

        self.store = Store.objects.create(
            name='Vendor Store',
            description='A store created for vendor tests.',
            owner=self.vendor,
        )

    def test_vendor_can_create_store(self):
        """Allow a vendor to create a new store linked to their
        account."""
        client = Client()
        client.force_login(self.vendor)

        response = client.post(
            '/create-store/',
            {'name': 'Second Store', 'description': 'This is another store.'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Store.objects.filter(
                name='Second Store',
                owner=self.vendor,
            ).exists()
        )

    def test_vendor_can_create_product_for_store(self):
        """Allow a vendor to add a product to one of their
        existing stores."""
        client = Client()
        client.force_login(self.vendor)

        response = client.post(
            '/create-product/',
            {
                'store_id': self.store.pk,
                'name': 'New Product',
                'description': 'A product for the vendor test.',
                'price': '12.50',
                'stock': 7,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Product.objects.filter(
                name='New Product',
                store=self.store,
            ).exists(),
        )


class StoreAndProductManagementTests(TestCase):
    """Test store and product management beyond creation
    flows."""

    def setUp(self):
        # Create the vendor, buyer, store, and product used in management
        # tests.
        self.vendor = User.objects.create_user(
            username='vendor_manage',
            email='vendor_manage@example.com',
            password='pass123',
        )
        self.buyer = User.objects.create_user(
            username='buyer_manage',
            email='buyer_manage@example.com',
            password='pass123',
        )
        self.store = Store.objects.create(
            name='Main Store',
            description='A store used for management tests.',
            owner=self.vendor,
        )
        self.product = Product.objects.create(
            store=self.store,
            name='Main Product',
            description='A product for management tests.',
            price=Decimal('18.00'),
            stock=8,
        )

    def test_buyer_can_view_products_from_different_stores(self):
        """Ensure a buyer can view product listings from available stores."""
        client = Client()
        client.force_login(self.buyer)
        session = client.session
        session['account_type'] = 'buyer'
        session.save()

        response = client.get('/buyer-page/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Main Product')
        self.assertContains(response, 'Add to Cart')

    def test_vendor_can_edit_and_delete_store(self):
        """Allow a vendor to update or remove a store that belongs to them."""
        client = Client()
        client.force_login(self.vendor)
        session = client.session
        session['account_type'] = 'vendor'
        session.save()

        response = client.post(
            f'/edit-store/{self.store.pk}/',
            {'name': 'Updated Store', 'description': 'Updated description'},
        )

        self.assertEqual(response.status_code, 302)
        self.store.refresh_from_db()
        self.assertEqual(self.store.name, 'Updated Store')

        delete_response = client.post(f'/delete-store/{self.store.pk}/')

        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Store.objects.filter(pk=self.store.pk).exists())

    def test_vendor_can_edit_and_delete_product(self):
        """Allow a vendor to update or remove a product from their store."""
        client = Client()
        client.force_login(self.vendor)
        session = client.session
        session['account_type'] = 'vendor'
        session.save()

        response = client.post(
            f'/edit-product/{self.product.pk}/',
            {
                'store_id': self.store.pk,
                'name': 'Updated Product',
                'description': 'Updated product description',
                'price': '22.00',
                'stock': 12,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Updated Product')

        delete_response = client.post(f'/delete-product/{self.product.pk}/')

        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())


class PersistentPurchaseTests(TestCase):
    """Test that purchase actions create durable order records."""

    def test_checkout_creates_persistent_order_records(self):
        """Record the order and order items when a buyer completes checkout."""
        buyer = User.objects.create_user(
            username='persistentbuyer',
            email='persistentbuyer@example.com',
            password='pass123',
        )
        store = Store.objects.create(
            name='Persistent Store',
            description='Store for order persistence tests.',
            owner=buyer,
        )
        product = Product.objects.create(
            store=store,
            name='Persistent Product',
            description='A product for order persistence tests.',
            price=Decimal('10.00'),
            stock=5,
        )

        client = Client()
        client.force_login(buyer)
        session = client.session
        session['cart'] = {str(product.pk): 2}
        session.save()

        response = client.post('/checkout/', {'confirm': 'yes'})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Order.objects.filter(user=buyer).exists())
        self.assertTrue(
            OrderItem.objects.filter(
                order__user=buyer, product=product).exists()
        )


class PasswordResetTests(TestCase):
    def setUp(self):
        """Create a user account used by password reset tests."""
        # Create the user who will request a reset token.
        self.user = User.objects.create_user(
            username='resetuser',
            email='resetuser@example.com',
            password='oldpass123',
        )

    def test_forgot_password_generates_token_and_allows_reset(self):
        """Send reset email, open link, and successfully change password."""
        # A valid reset request should create a token and send a full URL.
        client = Client()

        response = client.post(
            '/forgot-password/',
            {'email': 'resetuser@example.com'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('http://testserver/reset-password/', mail.outbox[0].body)
        self.assertTrue(ResetToken.objects.filter(user=self.user).exists())

        reset_line = [
            line for line in mail.outbox[0].body.splitlines()
            if 'http://testserver/reset-password/' in line
        ][0].strip()
        reset_url = reset_line.split('http://testserver', 1)[1]
        reset_path = urlparse(f'http://testserver{reset_url}').path

        reset_page = client.get(reset_path)
        self.assertEqual(reset_page.status_code, 200)

        reset_response = client.post(
            reset_path,
            {
                'new_password': 'newpass456',
                'confirm_password': 'newpass456',
            },
        )

        self.assertEqual(reset_response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass456'))

        token_record = ResetToken.objects.get(user=self.user)
        self.assertTrue(token_record.is_used)

    def test_reset_password_requires_matching_confirmation(self):
        """Reject reset attempts when password confirmation does not match."""
        client = Client()
        response = client.post(
            '/forgot-password/',
            {'email': 'resetuser@example.com'},
        )

        self.assertEqual(response.status_code, 200)

        reset_line = [
            line for line in mail.outbox[0].body.splitlines()
            if 'http://testserver/reset-password/' in line
        ][0].strip()
        reset_url = reset_line.split('http://testserver', 1)[1]
        reset_path = urlparse(f'http://testserver{reset_url}').path

        mismatch_response = client.post(
            reset_path,
            {'new_password': 'abc12345', 'confirm_password': 'different123'},
        )

        self.assertEqual(mismatch_response.status_code, 200)
        self.assertContains(mismatch_response, 'Passwords do not match')

    def test_expired_reset_token_redirects_to_login(self):
        """Redirect to login when the reset token is expired."""
        # An expired token should no longer allow reset access.
        client = Client()
        client.post('/forgot-password/', {'email': 'resetuser@example.com'})
        self.assertEqual(len(mail.outbox), 1)

        reset_line = [
            line for line in mail.outbox[0].body.splitlines()
            if 'http://testserver/reset-password/' in line
        ][0].strip()
        reset_url = reset_line.split('http://testserver', 1)[1]
        reset_path = urlparse(f'http://testserver{reset_url}').path

        token_record = ResetToken.objects.get(user=self.user)
        token_record.expiry_date = timezone.now() - timedelta(minutes=1)
        token_record.save(update_fields=['expiry_date'])

        response = client.get(reset_path)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/login/')
