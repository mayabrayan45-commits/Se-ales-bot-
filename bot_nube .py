"""
Bot de señales para GitHub Actions (SOLO AVISA, no opera).
Cada ejecución revisa la última vela cerrada de 15 min y avisa por Telegram
si hay señal. Datos: API pública de Coinbase (funciona desde servidores de EE. UU.).

Estrategia (pullback a favor de la tendencia):
  - EMA50 > EMA200: CALL cuando el RSI sube cruzando 35.
  - EMA50 < EMA200: PUT cuando el RSI baja cruzando 65.

MODE=senales (por defecto) o MODE=backtest (envía el resultado a Telegram).
"""
import os
import time
from datetime import datetime, timezone

import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MODE = os.getenv("MODE", "senales")

SYMBOLS = ["BTC-USD", "ETH-USD"]
GRAN = 900              # velas de 15 minutos (en segundos)
EXPIRY = 1              # expiración = 1 vela
RSI_LOW, RSI_HIGH = 35, 65
PAYOUT = 0.85           # revisa el pago real en Pocket Option
URL = "https://api.exchange.coinbase.com/products/{}/candles"
HEADERS = {"User-Agent": "senales-bot"}


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def get_candles(symbol, pages=1):
    """Cierres de velas ya cerradas, en orden, y la hora de cierre de la última."""
    rows = {}
    end = int(time.time())
    for _ in range(pages):
        start = end - 300 * GRAN
        r = requests.get(
            URL.format(symbol),
            params={"granularity": GRAN, "start": iso(start), "end": iso(end)},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        for c in r.json():  # [tiempo, low, high, open, close, volumen]
            rows[c[0]] = float(c[4])
        end = start
    now = time.time()
    times = sorted(t for t in rows if t + GRAN <= now)
    return [rows[t] for t in times], times[-1] + GRAN


def ema(values, period):
    k = 2 / (period + 1)
    out, e = [], values[0]
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, period=14):
    out = [None] * len(closes)
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / period, losses / period
    for i in range(period, len(closes)):
        if i > period:
            d = closes[i] - closes[i - 1]
            avg_g = (avg_g * (period - 1) + max(d, 0)) / period
            avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
        rs = avg_g / avg_l if avg_l else 100
        out[i] = 100 - 100 / (1 + rs)
    return out


def get_signal(e50, e200, r, i):
    if r[i] is None or r[i - 1] is None:
        return None
    if e50[i] > e200[i] and r[i - 1] < RSI_LOW <= r[i]:
        return "CALL"
    if e50[i] < e200[i] and r[i - 1] > RSI_HIGH >= r[i]:
        return "PUT"
    return None


def send(text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=15,
    )


def backtest():
    breakeven = 1 / (1 + PAYOUT)
    lines = [f"Backtest (pago {PAYOUT:.0%}): necesitas más de {breakeven:.1%} de acierto para no perder."]
    for sym in SYMBOLS:
        closes, _ = get_candles(sym, pages=10)
        e50, e200, r = ema(closes, 50), ema(closes, 200), rsi(closes)
        wins = total = 0
        for i in range(200, len(closes) - EXPIRY):
            s = get_signal(e50, e200, r, i)
            if not s:
                continue
            future = closes[i + EXPIRY]
            won = future > closes[i] if s == "CALL" else future < closes[i]
            wins += won
            total += 1
        if total:
            profit = wins * PAYOUT - (total - wins)
            lines.append(f"{sym}: {total} señales, acierto {wins / total:.1%}, resultado {profit:+.1f} unidades")
        else:
            lines.append(f"{sym}: sin señales en el periodo")
    return "\n".join(lines)


def run_once():
    for sym in SYMBOLS:
        try:
            closes, close_ts = get_candles(sym)
            if time.time() - close_ts >= GRAN:
                continue  # la última vela cerrada ya se revisó en otra ejecución
            e50, e200, r = ema(closes, 50), ema(closes, 200), rsi(closes)
            s = get_signal(e50, e200, r, len(closes) - 1)
            if s:
                send(f"{s} {sym}\nPrecio: {closes[-1]}\nExpiración sugerida: 15 min\nPrueba primero en DEMO.")
        except Exception as e:
            print("Error:", sym, e)


if __name__ == "__main__":
    if MODE == "backtest":
        text = backtest()
        print(text)
        send(text)
    else:
        run_once()
