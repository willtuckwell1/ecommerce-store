# E-commerce Store

A Django e-commerce application developed as a software engineering project.
It brings buyer and vendor flows together in one application, with a product
catalogue, basket, checkout and vendor management tools.

## Features

- Buyer and vendor registration and login
- Vendor store and product management
- Product browsing, reviews and stock-aware shopping cart
- Checkout, orders and invoice generation
- Password reset through Django's console email backend
- REST API endpoints for stores, products and reviews
- A small Reddit feed integration

This is a development project, not a production-ready shop. Checkout records an
order; no payment provider is configured. The included settings enable debug
mode and are for local use only. Do not deploy the project or use real customer
data without a separate security and production-readiness review.

## Local setup

You will need Python, MySQL or MariaDB, and the system libraries required by
`mysqlclient`. Create an empty database named `ecommerce_store` and a database
user with permission to access it. Use a password for the database account.

On macOS or Linux, from the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SECRET_KEY="$(openssl rand -hex 32)"
export DB_USER="your_database_user"
export DB_PASSWORD="your_database_password"
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Keep the same secret key between restarts if you
need existing sessions and signed data to remain valid. Supply the variables
again in a new terminal; don't commit real secrets or `.env` files.
`DB_HOST` and `DB_PORT` can be set if the database is not on
`localhost:3306`. Password reset emails are printed in the terminal during
local development.

To run the tests against a configured local MySQL/MariaDB server:

```sh
python manage.py test store_app.tests
```

The database user needs permission to create and remove Django's separate test
database. Do not point tests at a database containing data you need.
