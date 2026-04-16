module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  console.log('[analyze] API key present:', !!apiKey, '| prefix:', apiKey ? apiKey.slice(0, 10) : 'n/a');

  if (!apiKey) {
    return res.status(500).json({ error: 'API key not configured' });
  }

  // Vercel parses JSON bodies automatically when Content-Type is application/json.
  // Fall back to manual parsing if req.body is a raw string (e.g. edge cases).
  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch {
      return res.status(400).json({ error: 'Invalid JSON body' });
    }
  }
  if (!body || typeof body !== 'object') {
    return res.status(400).json({ error: 'Empty or invalid body' });
  }

  console.log('[analyze] incoming body keys:', Object.keys(body));

  // Enforce token limit; lock model server-side
  const sanitizedBody = {
    model: 'claude-sonnet-4-6',
    max_tokens: Math.min(typeof body.max_tokens === 'number' ? body.max_tokens : 1000, 1000),
    messages: body.messages,
  };

  if (!Array.isArray(sanitizedBody.messages) || sanitizedBody.messages.length === 0) {
    return res.status(400).json({ error: 'messages array is required' });
  }

  try {
    const upstream = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify(sanitizedBody),
    });

    console.log('[analyze] Anthropic status:', upstream.status);
    const data = await upstream.json();
    if (!upstream.ok) console.log('[analyze] Anthropic error body:', JSON.stringify(data));
    return res.status(upstream.status).json(data);
  } catch (err) {
    console.error('[analyze] fetch error:', err.message);
    return res.status(502).json({ error: 'Upstream request failed' });
  }
};
