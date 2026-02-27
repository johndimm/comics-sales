import { NextRequest, NextResponse } from 'next/server';
import { ebayBase, ebayToken } from '@/lib/server/ebay';

function htmlDecode(s: string) {
  return s
    .replaceAll('&amp;', '&')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'");
}

export async function GET(_: NextRequest, { params }: { params: { offerId: string } }) {
  try {
    const token = await ebayToken();
    const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'Content-Language': 'en-US' };
    const base = ebayBase();

    const ro = await fetch(`${base}/sell/inventory/v1/offer/${params.offerId}`, { headers: H, cache: 'no-store' });
    if (!ro.ok) return NextResponse.json({ error: await ro.text() }, { status: ro.status });
    const offer = await ro.json();
    const sku = offer?.sku || '';

    const ri = await fetch(`${base}/sell/inventory/v1/inventory_item/${sku}`, { headers: H, cache: 'no-store' });
    const inv = ri.ok ? await ri.json() : {};

    const title = (inv?.product || {}).title || '';
    const price = (((offer?.pricingSummary || {}).price || {}).value || '').toString();
    const description = (offer?.listingDescription || (inv?.product || {}).description || '').toString();

    return NextResponse.json({ offer, form: { title, price, description: htmlDecode(description) } });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}

export async function POST(req: NextRequest, { params }: { params: { offerId: string } }) {
  const body = await req.json();
  const title = String(body?.title || '');
  const price = String(body?.price || '');
  const description = String(body?.description || '');

  try {
    const token = await ebayToken();
    const H = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'Content-Language': 'en-US' };
    const base = ebayBase();

    const ro = await fetch(`${base}/sell/inventory/v1/offer/${params.offerId}`, { headers: H, cache: 'no-store' });
    if (!ro.ok) return NextResponse.json({ error: await ro.text() }, { status: ro.status });
    const offer = await ro.json();
    const sku = offer?.sku || '';

    const ri = await fetch(`${base}/sell/inventory/v1/inventory_item/${sku}`, { headers: H, cache: 'no-store' });
    if (!ri.ok) return NextResponse.json({ error: await ri.text() }, { status: ri.status });
    const inv = await ri.json();

    const qty = (((inv?.availability || {}).shipToLocationAvailability || {}).quantity || 1);
    const imageUrls = ((inv?.product || {}).imageUrls || []);
    const existingTitle = ((inv?.product || {}).title || '');
    const existingDesc = ((inv?.product || {}).description || '');

    const needsInventory = title !== existingTitle || description !== existingDesc;
    if (needsInventory) {
      const product: any = { title, description };
      if (Array.isArray(imageUrls) && imageUrls.length) product.imageUrls = imageUrls;
      const invPayload = { availability: { shipToLocationAvailability: { quantity: qty } }, product };
      const pu = await fetch(`${base}/sell/inventory/v1/inventory_item/${sku}`, {
        method: 'PUT', headers: H, body: JSON.stringify(invPayload),
      });
      if (!pu.ok) return NextResponse.json({ error: await pu.text() }, { status: pu.status });
    }

    offer.listingDescription = description;
    offer.pricingSummary = { price: { value: String(price), currency: 'USD' } };
    const po = await fetch(`${base}/sell/inventory/v1/offer/${params.offerId}`, {
      method: 'PUT', headers: H, body: JSON.stringify(offer),
    });
    if (!po.ok) return NextResponse.json({ error: await po.text() }, { status: po.status });

    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
