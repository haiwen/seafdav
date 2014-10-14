try:
    import cProfile as profile
except ImportError:
    import profile

import pstats
from cStringIO import StringIO

def do_profile(func):
    def wrapper(*args, **kwargs):
        profiler = profile.Profile()
        ret = profiler.runcall(func, *args, **kwargs)
        profiler.create_stats()
        io = StringIO()
        stats = pstats.Stats(profiler, stream=io)
        stats.sort_stats('cumu')
        stats.print_callees()
        stats.print_stats(100)
        with open('/tmp/dav.log', 'w') as fp:
            fp.write(io.getvalue())
        return ret

    return wrapper
