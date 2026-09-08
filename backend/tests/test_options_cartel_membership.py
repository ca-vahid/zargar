import httpx
import pytest

from zargar.techniques.options_cartel.membership import INDUSTRY, ORIGIN, capture_membership, stock_mapping
from zargar.techniques.options_cartel.service import CartelService, ResearchInput

from .test_options_cartel_api import research_payload
from .test_options_cartel_screen import inputs

STOCK = ORIGIN+'/symbols/NASDAQ-TEST/'
GROUP = ORIGIN+INDUSTRY+'semiconductors/'


def stock_html(canonical=STOCK):
    return f'<link rel="canonical" href="{canonical}"><a href="{GROUP}">Semiconductors</a>'


@pytest.mark.parametrize('html', [stock_html('https://example.test/'),
    stock_html()+f'<a href="{ORIGIN+INDUSTRY}other/">Other</a>', '<html>Challenge</html>'])
def test_missing_or_ambiguous_classification_is_rejected(html):
    with pytest.raises(ValueError):
        stock_mapping(html, STOCK)


@pytest.mark.parametrize('member', ['NASDAQ:TEST', 'NYSE:TEST'])
async def test_reciprocal_mapping_persists_only_matching_exchange_and_symbol(engine, member):
    service = CartelService(engine)
    body = ResearchInput.model_validate(research_payload())
    def respond(request):
        html = stock_html() if str(request.url) == STOCK else \
            f'<link rel="canonical" href="{GROUP}"><table><tr data-rowkey="{member}"></tr></table>'
        return httpx.Response(200, text=html)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        if member != 'NASDAQ:TEST':
            with pytest.raises(ValueError, match='does not confirm'):
                await capture_membership(service, 'NASDAQ', 'TEST', client=client)
            return
        saved = await capture_membership(service, 'NASDAQ', 'TEST', client=client, clock=lambda: body.as_of_ms)
    assert saved['result']['industry'] == 'Semiconductors'
    assert saved['result']['placesOrders'] is False
    analyzed = await service.analyze(body.model_copy(update={'membership_snapshot_id': saved['runId']}))
    facts = analyzed['config']['inputs']['facts']
    assert facts['membership_snapshot_id'] == saved['runId']
    assert facts['industry'] == 'Semiconductors'
    assert facts['observed_at'] == body.facts.observed_at
    with pytest.raises(ValueError, match='this symbol'):
        await service.analyze(body.model_copy(update={'membership_snapshot_id': saved['runId'],
            'facts': body.facts.model_copy(update={'symbol': 'OTHER'})}))


@pytest.mark.parametrize('offset,expected', [(0, 'pass'), (1, 'unknown'), (-9*86_400_000, 'unknown')])
def test_mapping_age_is_independent_of_new_capitalization(offset, expected):
    from zargar.techniques.options_cartel.rules import CartelRules
    from zargar.techniques.options_cartel.screen import screen_listing
    bars, facts, indices, at = inputs()
    facts = facts.model_copy(update={'membership_observed_at': at+offset, 'membership_snapshot_id': 'mapping'})
    result = screen_listing(bars, facts, indices, CartelRules(), at)
    assert next(g for g in result['gates'] if g['label'].startswith('Industry ranks'))['status'] == expected
    assert next(g for g in result['gates'] if 'capitalization' in g['label'])['status'] == 'pass'
    if expected == 'unknown':
        assert result['facts']['industry'] is None
