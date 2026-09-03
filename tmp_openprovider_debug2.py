from dotenv import load_dotenv
import json, asyncio
load_dotenv('.env', override=True)
from app.integrations.openprovider import client

async def dump(domain, include_aftermarket):
    name, ext = domain.rsplit('.', 1)
    print('DOMAIN', domain, 'include_aftermarket=', include_aftermarket)
    try:
        check = await client.check_domain(name, ext, include_aftermarket=include_aftermarket)
        print('CHECK result keys', sorted(check.keys()))
        print('CHECK RAW', json.dumps(check, indent=2)[:8000])
        print('extract_create_price_details', client.extract_create_price_details(check))
        print('extract_renewal_price_details', client.extract_renewal_price_details(check))
    except Exception as e:
        print('CHECK error', repr(e))
    try:
        quote_create = await client.get_domain_price(name, ext, operation='create', period=1)
        print('GET_CREATE RAW', json.dumps(quote_create, indent=2)[:8000])
    except Exception as e:
        print('GET_CREATE error', repr(e))
    try:
        quote_renew = await client.get_domain_price(name, ext, operation='renew', period=1)
        print('GET_RENEW RAW', json.dumps(quote_renew, indent=2)[:8000])
    except Exception as e:
        print('GET_RENEW error', repr(e))

async def main():
    for inc in [False, True]:
        await dump('swara.org', inc)

asyncio.run(main())
