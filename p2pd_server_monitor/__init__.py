
import sys

if not '-m' in sys.argv:
    from .dealer.dealer import *
    from .worker.worker import *