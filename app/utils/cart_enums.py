"""Enum definitions for the shopping cart subsystem."""

from __future__ import annotations

from enum import Enum


class CartProductType(str, Enum):
    """Discriminator for the type of product in a cart item."""

    DOMAIN_LISTING = "DOMAIN_LISTING"
    TECHNOLOGY = "TECHNOLOGY"
    DOMAIN_REGISTRATION = "DOMAIN_REGISTRATION"
    VENTURE_DEAL = "VENTURE_DEAL"


class CartCheckoutStatus(str, Enum):
    """Status of a cart checkout order."""

    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
