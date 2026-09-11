"""Razorpay SDK client configuration tests."""

from __future__ import annotations

import certifi

from app.integrations.razorpay import client as rzp_client


def test_create_client_uses_verified_tls_ca_bundle():
    client = rzp_client.create_client()

    expected = True if rzp_client.truststore is not None else certifi.where()
    assert client.cert_path == expected
