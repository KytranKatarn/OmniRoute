"""
Store Builder Module
====================
E-commerce store building with product management and payments.

Features:
- Create and manage online stores
- Product catalog management
- Order processing
- Payment integrations (Stripe, PayPal)
- Printful integration for print-on-demand

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from .routes import store_builder_bp

__all__ = ['store_builder_bp']
