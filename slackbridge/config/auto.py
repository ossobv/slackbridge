from . import env, ini
from .ini import load as ini_load


def load():
    for mod in (env, ini):
        try:
            configs = mod.load()
        except StopIteration:
            pass
        else:
            return configs

    raise StopIteration()
