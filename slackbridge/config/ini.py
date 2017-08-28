from os import environ

from .data import BridgeConfig, BridgeConfigs, BridgeEndConfig


class BridgeConfigsFromIni(BridgeConfigs):
    def __init__(self, inifile):
        self._res = BridgeConfigs()
        self._ini = inifile
        self._load()

    def get(self):
        return self._res

    def _load(self):
        for section in self._ini.sections():
            self._load_section(section, self._ini[section])

    def _load_section(self, name, section):
        pair = []
        for L in 'AB':
            def get(key):
                return section['{}.{}'.format(L, key)].strip()

            end = BridgeEndConfig()
            end.WEBHOOK_IN_URL = get('webhook_in_url')
            end.WEBHOOK_OUT_TOKEN = get('webhook_out_token')
            end.CHANNEL = get('channel')
            end.PEERNAME = get('peername')
            end.WEBAPI_TOKEN = get('webapi_token')
            pair.append(end)

        self._res.add_config(BridgeConfig(name, *pair))


def configs_from_inifile(inifile):
    try:
        from configparser import ConfigParser, ExtendedInterpolation
    except ImportError:
        import errno
        raise IOError(
            errno.ENOENT,
            'Missing ConfigParser and ExtendedInterpolation: '
            'please use python3+')
    else:
        parser = ConfigParser(
            allow_no_value=False,     # don't allow "key" without "="
            delimiters=('=',),        # inifile "=" between key and value
            comment_prefixes=(';',),  # only ';' for comments (fixes #channel)
            inline_comment_prefixes=(';',),     # comments after lines
            interpolation=ExtendedInterpolation(),
            empty_lines_in_values=False)  # empty line means new key
        parser.read_file(inifile)
        return BridgeConfigsFromIni(parser).get()


def load():
    filename = environ.get('SLACKBRIDGE_INIFILE', './slackbridge.ini')
    with open(filename) as inifile:
        return configs_from_inifile(inifile)
