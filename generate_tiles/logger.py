import sys
import logging

logging.basicConfig(format='%(asctime)s [%(levelname)s]  %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
logger = logging.getLogger(vars(sys.modules[__name__])['__package__'])
logger.setLevel(logging.INFO)