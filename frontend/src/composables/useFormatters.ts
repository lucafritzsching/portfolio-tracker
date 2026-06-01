export function useFormatters() {
  const fmt = (n: number | null | undefined) =>
    n != null ? n.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '–'

  const fmtPct = (n: number | null | undefined) =>
    n != null ? `${n >= 0 ? '+' : ''}${n.toFixed(2)}%` : '–'

  const fmtCurrency = (n: number | null | undefined) =>
    n != null ? `€ ${fmt(n)}` : '–'

  const fmtDate = (d: string | null | undefined) => {
    if (!d) return '–'
    const date = new Date(d)
    return date.toLocaleDateString('de-DE')
  }

  const fmtLargeNumber = (n: number | null | undefined) => {
    if (n == null) return '–'
    if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}T`
    if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`
    if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
    return fmt(n)
  }

  return { fmt, fmtPct, fmtCurrency, fmtDate, fmtLargeNumber }
}
