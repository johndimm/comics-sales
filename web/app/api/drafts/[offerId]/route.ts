import { NextRequest, NextResponse } from 'next/server';

const UPSTREAM = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8080';

export async function GET(_: NextRequest, { params }: { params: { offerId: string } }) {
  try {
    const [offerRes, editRes] = await Promise.all([
      fetch(`${UPSTREAM}/api-drafts/offer/${params.offerId}`, { cache: 'no-store' }),
      fetch(`${UPSTREAM}/api-drafts/edit/${params.offerId}`, { cache: 'no-store' }),
    ]);

    const offer = await offerRes.json();
    const editHtml = await editRes.text();

    // Parse title/price/description from legacy edit form HTML (bridge step during migration)
    const titleMatch = editHtml.match(/<input name='title' value='([^']*)'/);
    const priceMatch = editHtml.match(/<input name='price' value='([^']*)'/);
    const descMatch = editHtml.match(/<textarea name='description'>([\s\S]*?)<\/textarea>/);

    return NextResponse.json({
      offer,
      form: {
        title: titleMatch?.[1] ?? '',
        price: priceMatch?.[1] ?? '',
        description: descMatch?.[1] ?? '',
      },
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}

export async function POST(req: NextRequest, { params }: { params: { offerId: string } }) {
  const body = await req.json();
  const payload = new URLSearchParams();
  payload.set('title', String(body?.title ?? ''));
  payload.set('price', String(body?.price ?? ''));
  payload.set('description', String(body?.description ?? ''));

  try {
    const res = await fetch(`${UPSTREAM}/api-drafts/edit/${params.offerId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: payload.toString(),
      redirect: 'manual',
    });

    if (res.status >= 300 && res.status < 400) {
      return NextResponse.json({ ok: true, redirected: true });
    }

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json({ error: text.slice(0, 1000) }, { status: res.status });
    }

    return NextResponse.json({ ok: true });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
