from dotenv import load_dotenv
import json, asyncio
load_dotenv('.env', override=True)
from app.integrations.openprovider import client

async def dump(domain):
    name, ext = domain.rsplit('.', 1)
    print('DOMAIN', domain)
    try:
        check = await client.check_domain(name, ext, include_aftermarket=False)
        print('CHECK keys', sorted(check.keys()))
        print('PRICE', json.dumps(check.get('price'), indent=2))
        print('PREMIUM', json.dumps(check.get('premium'), indent=2))
        print('IS_PREMIUM', check.get('is_premium'))
        print('extract_create_price_details', client.extract_create_price_details(check))
        print('extract_renewal_price_details', client.extract_renewal_price_details(check))
    except Exception as e:
        print('CHECK error', repr(e))
    try:
        quote = await client.get_domain_price(name, ext, operation='renew', period=1)
        print('GET_RENEW keys', sorted(quote.keys()))
        print('GET_RENEW PRICE', json.dumps(quote.get('price'), indent=2))
        print('GET_RENEW PREMIUM', json.dumps(quote.get('premium'), indent=2))
        print('GET_RENEW RAW', json.dumps(quote, indent=2)[:4000])
    except Exception as e:
        print('GET renew error', repr(e))

async def main():
    for d in ['swara.org','hustler.net','hustler.co']:
        await dump(d)

asyncio.run(main())
