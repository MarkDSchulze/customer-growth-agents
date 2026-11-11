import { NextRequest, NextResponse } from 'next/server';

async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const { path } = await context.params;
  if (!['v1','v2'].includes(path[0]) || path.some(p => !/^[a-zA-Z0-9_.:-]+$/.test(p))) {
    return NextResponse.json({detail: 'INVALID_PATH'}, {status: 400});
  }
  const authorization = request.headers.get('authorization');
  if (!authorization) return NextResponse.json({detail: 'AUTHENTICATION_REQUIRED'}, {status: 401});
  const target = new URL(path.join('/'), `${process.env.GROWTH_API_URL ?? 'http://127.0.0.1:8000'}/`);
  target.search = request.nextUrl.search;
  const headers = new Headers({'Authorization': authorization, 'Content-Type': 'application/json'});
  for (const name of ['Idempotency-Key', 'X-Correlation-ID']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const response = await fetch(target, {
      method: request.method, headers, cache: 'no-store',
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text(),
      signal: AbortSignal.timeout(30000), redirect: 'error',
    });
    return new NextResponse(await response.text(), {
      status: response.status, headers: {'Content-Type': response.headers.get('content-type') ?? 'application/json', 'Cache-Control': 'no-store'},
    });
  } catch {
    return NextResponse.json({detail: 'GROWTH_API_UNAVAILABLE'}, {status: 502});
  }
}
export {proxy as GET, proxy as POST, proxy as PUT};
