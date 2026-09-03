"""DNS TXT verification for domain listings."""

from __future__ import annotations

import logging

import dns.exception
import dns.resolver

logger = logging.getLogger(__name__)

# Render/cloud hosts: use public resolvers (system DNS can be flaky)
_PUBLIC_RESOLVERS = ["8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1"]


def _resolver() -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver(configure=True)
    resolver.nameservers = list(_PUBLIC_RESOLVERS)
    resolver.timeout = 10
    resolver.lifetime = 15
    return resolver


def domain_has_verification_txt(fqdn: str, expected_record: str) -> bool:
    """True if any TXT record on fqdn contains the expected verification string."""
    fqdn = fqdn.strip().lower().rstrip(".")
    expected = expected_record.strip()
    if not expected:
        return False

    # Also accept TXT on www when verifying apex (common misconfiguration)
    hosts = [fqdn] if fqdn else []
    if fqdn and not fqdn.startswith("www."):
        hosts.append(f"www.{fqdn}")
    if not hosts:
        return False

    resolver = _resolver()
    for host in hosts:
        try:
            answers = resolver.resolve(host, "TXT")
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.exception.Timeout,
        ) as exc:
            logger.info("DNS TXT lookup miss for %s: %s", host, exc)
            continue
        except Exception as exc:
            logger.warning("DNS TXT lookup error for %s: %s", host, exc)
            continue

        for rdata in answers:
            for chunk in rdata.strings:
                try:
                    txt = chunk.decode("utf-8", errors="ignore").strip()
                except AttributeError:
                    txt = str(chunk).strip()
                if txt == expected or expected in txt:
                    logger.info("DNS TXT verified for %s", host)
                    return True
    return False
