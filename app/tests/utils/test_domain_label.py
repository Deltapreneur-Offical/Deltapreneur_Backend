"""Unit tests for Domain Register SLD sanitization. No database."""

from app.utils.domain_label import compose_search_fqdn, sanitize_extension, sanitize_sld


def test_spaces_and_punctuation_are_dropped():
    assert sanitize_sld("a coffee shop near collage") == "acoffeeshopnearcollage"
    assert sanitize_sld("  A Coffee-Shop, near collage!  ") == "acoffee-shopnearcollage"
    assert sanitize_sld("o'reilly & tea") == "oreillytea"


def test_tld_is_split_off_the_label():
    assert sanitize_sld("a coffee shop.com") == "acoffeeshop"
    assert sanitize_extension("a coffee shop.com") == "com"
    assert compose_search_fqdn("a coffee shop near collage") == "acoffeeshopnearcollage.com"
    assert compose_search_fqdn("my shop.co.uk") == "myshop.co.uk"


def test_empty_and_hyphen_only_are_rejected():
    assert sanitize_sld("") == ""
    assert sanitize_sld("   ") == ""
    assert sanitize_sld("!!! ???") == ""
    assert sanitize_sld("---") == ""
    assert compose_search_fqdn("***") == ""


def test_ascii_only_and_length_cap():
    assert sanitize_sld("café shop") == "cafshop"
    assert len(sanitize_sld("a" * 80)) == 63
    assert sanitize_sld("-hello-world-") == "hello-world"
