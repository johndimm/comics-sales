const BASE = (process.env.EBAY_ENV || 'production').toLowerCase().startsWith('prod')
  ? 'https://api.ebay.com'
  : 'https://api.sandbox.ebay.com';

export function ebayBase() {
  return BASE;
}

export async function ebayToken() {
  const cid = process.env.EBAY_CLIENT_ID;
  const sec = process.env.EBAY_CLIENT_SECRET;
  const rt = process.env.EBAY_REFRESH_TOKEN;
  if (!cid || !sec || !rt) throw new Error('Missing EBAY_CLIENT_ID/SECRET/REFRESH_TOKEN');
  const auth = Buffer.from(`${cid}:${sec}`).toString('base64');
  const scope = [
    'https://api.ebay.com/oauth/api_scope',
    'https://api.ebay.com/oauth/api_scope/sell.inventory',
    'https://api.ebay.com/oauth/api_scope/sell.account',
    'https://api.ebay.com/oauth/api_scope/sell.fulfillment',
  ].join(' ');
  const form = new URLSearchParams({ grant_type: 'refresh_token', refresh_token: rt, scope });
  const res = await fetch(`${BASE}/identity/v1/oauth2/token`, {
    method: 'POST',
    headers: { Authorization: `Basic ${auth}`, 'content-type': 'application/x-www-form-urlencoded' },
    body: form.toString(),
  });
  if (!res.ok) throw new Error(`eBay token failed: ${res.status} ${await res.text()}`);
  const j = await res.json();
  return j.access_token as string;
}
