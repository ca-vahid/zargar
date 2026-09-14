"""FIFO attribution from actual fills, including entry fees on carried lots."""
import math
from collections import defaultdict, deque


def summarize_fills(rows, begins, cutoff, ownership=None):
    lots, assets, issues = defaultdict(deque), {}, []
    for fill, order in sorted(rows, key=lambda r: (r[0].ts, r[0].id)):
        if fill.ts > cutoff:
            continue
        if fill.symbol != order.symbol or fill.portfolio_id != order.portfolio_id or fill.side != order.side:
            issues.append(f'Execution {fill.id} disagrees with its order')
            continue
        if not all(math.isfinite(x) for x in (fill.qty, fill.price, fill.commission)) or fill.qty <= 0 or fill.price <= 0 or fill.commission < 0:
            issues.append(f'Execution {fill.id} has invalid accounting values')
            continue
        key = (order.symbol, order.sec_type, (ownership or {}).get(order.id))
        asset = assets.setdefault(key, {'symbol': order.symbol, 'secType': order.sec_type, 'planId': key[2],
            'grossRealized': 0., 'realizedFees': 0., 'feesPaidToday': 0., 'entryOrders': set(),
            'exitOrders': set(), 'executionIds': [], 'remainingQty': 0.})
        today = fill.ts >= begins
        if today:
            asset['feesPaidToday'] += fill.commission
            asset['executionIds'].append(fill.id)
            asset['entryOrders' if fill.side == 'BUY' else 'exitOrders'].add(order.id)
        if fill.side == 'BUY':
            lots[key].append([fill.qty, fill.price, fill.commission/fill.qty, order.id])
        elif fill.side == 'SELL':
            left = fill.qty
            while left > 1e-9 and lots[key]:
                lot = lots[key][0]
                quantity = min(left, lot[0])
                if today:
                    asset['grossRealized'] += quantity*(fill.price-lot[1])*(100 if order.sec_type == 'OPT' else 1)
                    asset['realizedFees'] += quantity*(lot[2]+fill.commission/fill.qty)
                lot[0] -= quantity
                left -= quantity
                if lot[0] <= 1e-9:
                    lots[key].popleft()
            if left > 1e-9:
                issues.append(f'{order.symbol}: exit exceeds reconstructed long holdings')
        else:
            issues.append(f'{order.symbol}: unsupported side')
    result = []
    for key, asset in assets.items():
        asset['remainingQty'] = sum(lot[0] for lot in lots[key])
        asset['remainingCost'] = sum(lot[0]*lot[1]*(100 if key[1] == 'OPT' else 1) for lot in lots[key])
        asset['openEntryFees'] = sum(lot[0]*lot[2] for lot in lots[key])
        asset['netRealized'] = asset['grossRealized']-asset['realizedFees']
        asset['entryOrders'] = sorted(asset['entryOrders'])
        asset['exitOrders'] = sorted(asset['exitOrders'])
        if asset['executionIds'] or asset['remainingQty']:
            result.append(asset)
    return result, issues
