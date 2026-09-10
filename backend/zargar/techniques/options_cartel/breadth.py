"""Completed-session equal-weight context. Advisory only, never an entry gate."""
from ...marketstructure.indicators import ema_series
from .screen import _latest_session


def read_breadth(histories, at):
    reads = {}
    for symbol in ('SPY', 'RSP', 'QQQ', 'QQQE'):
        bars = histories.get(symbol, [])
        if len(bars) < 21 or bars[-1].session != _latest_session(at):
            reads[symbol] = {'available': False, 'reason': 'Current completed session and 21-session warm-up required'}
            continue
        close = bars[-1].close
        ema21 = ema_series([b.close for b in bars], 21)[-1]
        reads[symbol] = {'available': True, 'session': bars[-1].session.isoformat(), 'close': close,
                         'changePct': (close/bars[-2].close-1)*100, 'aboveEma21': close > ema21}
    return {'advisoryOnly': True, 'indices': reads,
            'nymo': {'available': False, 'reason': 'No verified NYMO source configured; no proxy is substituted.'},
            'interpretation': 'Compare SPY/RSP and QQQ/QQQE participation. This is context, not a signal or a sizing multiplier.'}
