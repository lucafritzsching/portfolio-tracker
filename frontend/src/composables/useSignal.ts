import type { Position, Signal } from '@/types'

export function useSignal() {
  const getSignal = (pos: Position): Signal => {
    const avgBuy = pos.avg_buy_price ?? pos.manual_buy_price
    if (avgBuy != null && pos.current_price != null) {
      const ret = (pos.current_price - avgBuy) / avgBuy * 100
      if (ret > 20) return { label: 'Verkaufen', cls: 'sell' }
      if (ret < -12) return { label: 'Nachkaufen', cls: 'buy' }
    }
    const dayChange = pos.day_change ?? 0
    if (Math.abs(dayChange) > 4) return { label: 'Beobachten', cls: 'watch' }
    return { label: 'Halten', cls: 'hold' }
  }

  return { getSignal }
}
