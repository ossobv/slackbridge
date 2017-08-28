from os import environ as env

from .data import BridgeConfig, BridgeConfigs, BridgeEndConfig


def load():
    configs = BridgeConfigs()
    try:
        idx = 1

        while True:
            pair = []
            for L in 'AB':
                end = BridgeEndConfig()
                end.WEBHOOK_OUT_TOKEN = env[
                    'PORTAL_{}_SIDE_{}_WEBHOOK_OUT_TOKEN'.format(idx, L)]
                end.WEBHOOK_IN_URL = env[
                    'PORTAL_{}_SIDE_{}_WEBHOOK_IN_URL'.format(idx, L)]
                end.CHANNEL = env[
                    'PORTAL_{}_SIDE_{}_CHANNEL_NAME'.format(idx, L)]
                end.PEERNAME = env[  # GROUP_NAME is "them", i.e. peername
                    'PORTAL_{}_SIDE_{}_GROUP_NAME'.format(idx, L)]
                end.WEBAPI_TOKEN = env[
                    'PORTAL_{}_SIDE_{}_WEB_API_TOKEN'.format(idx, L)]
                pair.append(end)

            name = '{}-{}'.format(pair[1].PEERNAME, pair[0].PEERNAME)
            configs.add_config(BridgeConfig(name, *pair))
            idx += 1
    except KeyError:
        # Stop at first keyerror.
        pass

    if not len(configs):
        raise StopIteration('No SlackBridge config found in ENV')

    return configs
