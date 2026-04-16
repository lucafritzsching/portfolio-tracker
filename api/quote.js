export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { symbol } = req.query;
  if (!symbol || typeof symbol !== 'string' || !/^[A-Z0-9.^=-]{1,20}$/i.test(symbol)) {
    return res.status(400).json({ error: 'Invalid or missing symbol' });
  }

  const apiKey = process.env.FINNHUB_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'API key not configured' });
  }

  try {
    const upstream = await fetch(
      `https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(symbol.toUpperCase())}&token=${apiKey}`
    );
    const data = await upstream.json();

    // Finnhub returns { c: current, d: change, dp: change%, h, l, o, pc: prev close, t }
    // c === 0 means symbol not found
    if (!upstream.ok || data.c === 0) {
      return res.status(404).json({ error: 'Symbol not found' });
    }

    return res.status(200).json({
      currentPrice: data.c,
      dayChange: data.dp,      // percent, e.g. 1.23
      previousClose: data.pc,
    });
  } catch {
    return res.status(502).json({ error: 'Upstream request failed' });
  }
}
