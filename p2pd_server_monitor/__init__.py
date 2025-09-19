
import sys

if not '-m' in sys.argv:
    from .dealer_server import *
    from .worker_process import *