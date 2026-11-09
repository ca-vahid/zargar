"""GC pauses (2026-11-09): survivors are frozen out of session collections, and the nightly compact still
collects cycles that died after a freeze."""
import gc
import weakref

from zargar import gctune


class _Node:
    def __init__(self):
        self.peer = None


def teardown_function(_fn):
    gc.unfreeze()


def test_compact_moves_survivors_out_of_the_session_collections():
    keep = [_Node() for _ in range(200_000)]          # long-lived tracked state, like bars/plans/positions
    out = gctune.compact()
    assert out["frozen"] >= 200_000
    assert len(gc.get_objects(generation=2)) < 50_000  # a full collection no longer walks the frozen state
    assert len(keep) == 200_000


def test_nightly_compact_collects_a_cycle_that_died_after_the_freeze():
    a, b = _Node(), _Node()
    a.peer, b.peer = b, a                             # a reference cycle: only the cyclic GC can free it
    probe = weakref.ref(a)
    gctune.compact()                                  # frozen while alive
    del a, b
    gc.collect()
    assert probe() is not None                        # frozen: session collections leave it alone
    gctune.compact()                                  # nightly: unfreeze -> collect -> freeze
    assert probe() is None


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _Scheduler:
    def __init__(self):
        self.jobs = {}

    def register(self, name, at, fn, *, weekdays_only=True):
        self.jobs[name] = (at, fn, weekdays_only)


class _Engine:
    def __init__(self, **settings):
        self.settings = _Settings(settings)
        self.scheduler = _Scheduler()


async def test_attach_registers_the_nightly_job_and_honours_the_switch():
    eng = _Engine()
    gctune.attach(eng)
    at, fn, weekdays_only = eng.scheduler.jobs["gc_compact"]
    assert at == "20:00" and weekdays_only is False
    assert (await fn())["frozen"] > 0
    eng.settings["ops.gc_freeze"] = False
    assert (await fn()) == {"skipped": "ops.gc_freeze off"}
    off = _Engine(**{"ops.gc_freeze": False})
    gctune.attach(off)
    assert off.scheduler.jobs == {}
