"""
Temporary diagnostic script — traces the FULL OpenProvider pricing pipeline
for premium domains: check response -> extract_renewal_price_details ->
GetPrice(operation=renew) -> what the backend would return.

Run:  python tmp_premium_debug.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
import json, asyncio
load_dotenv('.env', override=True)

from app.integrations.openprovider import client

SEP = "\n" + "=" * 80 + "\n"

async def dump(domain):
    name, ext = domain.rsplit('.', 1)
    print(SEP + f"DOMAIN: {domain}  (name={name!r}  ext={ext!r})" + SEP)

    # 1. Raw check response
    check = None
    try:
        check = await client.check_domain(name, ext, include_aftermarket=False)
        print("[CHECK] Top-level keys:", sorted(check.keys()))
        print("[CHECK] status:", check.get("status"))
        print("[CHECK] is_premium:", check.get("is_premium"))
        print()
        print("[CHECK] price block (FULL):")
        print(json.dumps(check.get("price"), indent=2, default=str))
        print()
        print("[CHECK] premium block (FULL):")
        print(json.dumps(check.get("premium"), indent=2, default=str))
    except Exception as e:
        print("[CHECK] ERROR:", repr(e))

    if check is not None:
        # 2. extract_renewal_price_details
        try:
            renew_extracted = client.extract_renewal_price_details(check)
            print()
            renew_val, renew_cur = renew_extracted
            print(f"[EXTRACT_RENEWAL] extract_renewal_price_details -> {renew_extracted}")
            if renew_val is None:
                print("[EXTRACT_RENEWAL] -> None: no explicit renew key in check response.")
                price_block = check.get("price") or {}
                reseller = price_block.get("reseller") or {}
                product = price_block.get("product") or {}
                prem = check.get("premium") or {}
                pp = prem.get("price") or {}
                print("  price.reseller.renew =", reseller.get("renew"))
                print("  price.product.renew  =", product.get("renew"))
                print("  price.renew          =", price_block.get("renew"))
                print("  premium.price.renew  =", pp.get("renew") if isinstance(pp, dict) else "N/A")
            else:
                print(f"[EXTRACT_RENEWAL] -> renew={renew_val}  currency={renew_cur}")
        except Exception as e:
            print("[EXTRACT_RENEWAL] ERROR:", repr(e))

        # 3. extract_create_price_details
        try:
            create_extracted = client.extract_create_price_details(check)
            print()
            print(f"[EXTRACT_CREATE] -> unit={create_extracted[0]}  currency={create_extracted[1]}  source={create_extracted[2]}")
        except Exception as e:
            print("[EXTRACT_CREATE] ERROR:", repr(e))

    # 4. GetPrice(operation=renew) with ACTUAL domain name
    print()
    print(f"[GETPRICE_RENEW] Calling GetPrice(name={name!r}, ext={ext!r}, operation=renew, period=1) ...")
    try:
        ren_quote = await client.get_domain_price(name, ext, operation="renew", period=1)
        print("[GETPRICE_RENEW] Full response:")
        print(json.dumps(ren_quote, indent=2, default=str)[:5000])
        ren_unit, ren_curr = client.extract_reseller_price_details(ren_quote)
        print(f"[GETPRICE_RENEW] extract_reseller_price_details -> unit={ren_unit}  currency={ren_curr}")
    except Exception as e:
        print("[GETPRICE_RENEW] ERROR:", repr(e))

    # 5. GetPrice(operation=renew) with "example" (the OLD broken name)
    print()
    print(f"[GETPRICE_RENEW_OLD] Calling GetPrice(name='example', ext={ext!r}, operation=renew) ...")
    try:
        old_quote = await client.get_domain_price("example", ext, operation="renew", period=1)
        old_unit, old_curr = client.extract_reseller_price_details(old_quote)
        print(f"[GETPRICE_RENEW_OLD] extract_reseller_price_details -> unit={old_unit}  currency={old_curr}")
        print("[GETPRICE_RENEW_OLD] Full response:")
        print(json.dumps(old_quote, indent=2, default=str)[:3000])
    except Exception as e:
        print("[GETPRICE_RENEW_OLD] ERROR:", repr(e))

async def main():
    domains = ["swaraj.co", "swaraj.link", "swara.org", "hustler.net", "hustler.co"]
    for d in domains:
        await dump(d)
        await asyncio.sleep(0.5)

asyncio.run(main())
