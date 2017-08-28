class BridgeEndConfig(object):
    """
    All settings are mandatory, except the WEBAPI_TOKEN. However, it is
    preferred to have access to a limited user to supply info about
    @USERS, @CHANNELS, Avatars and the list of people online.

    Use a "Bot user" (single channel guest) in your #shared-peername
    channel for limited access.
    """
    # From Slack to us:
    #   '0123ABCDabcdefghijklmnop'
    WEBHOOK_OUT_TOKEN = None
    # From us to Slack:
    #   'https://hooks.slack.com/services/xxxxxxxxxxx'
    WEBHOOK_IN_URL = None
    # What channel name we use when writing to Slack:
    #   'C012345ZYX' or '#shared-peername'
    CHANNEL = None
    # The "@mention" to @channel only the other side:
    #   'othercompany'
    PEERNAME = None
    # WebAPI token for information gathering:
    #   'xoxp-0123456789-0123456789-0123456789-abcdef'
    WEBAPI_TOKEN = None


class BridgeConfig(object):
    def __init__(self, name, side_a, side_b):
        self.NAME = name
        self.SIDE_A = side_a
        self.SIDE_B = side_b

    def __str__(self):
        return '<{}: {}->@{}, {}->@{}>'.format(
            self.NAME, self.SIDE_A.CHANNEL, self.SIDE_A.PEERNAME,
            self.SIDE_B.CHANNEL, self.SIDE_B.PEERNAME)


class BridgeConfigs(object):
    """
    Settings object holding all of the settings to be consumed by actual
    constructors of the actual slack communication.
    """
    def __init__(self):
        self._pairs = []

    def __len__(self):
        return len(self._pairs)  # also for boolean check

    def add_config(self, bridgeconfig):
        self._pairs.append(bridgeconfig)

    def to_config_dict(self):
        """
        Convert settings into old-style CONFIG dict.
        """
        ret = {}
        for pair in self._pairs:
            for our, their in (
                    (pair.SIDE_A, pair.SIDE_B), (pair.SIDE_B, pair.SIDE_A)):
                ret[our.WEBHOOK_OUT_TOKEN] = {
                    'iwh_url': their.WEBHOOK_IN_URL,
                    'iwh_update': {
                        'channel': their.CHANNEL,
                        '_atchannel': our.PEERNAME,
                    },
                    'owh_linked': their.WEBHOOK_OUT_TOKEN,
                }
                if our.WEBAPI_TOKEN:
                    ret[our.WEBHOOK_OUT_TOKEN]['wa_token'] = our.WEBAPI_TOKEN

        return ret
