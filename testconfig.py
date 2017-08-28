# Example script to check that your config still looks like it did
# before upgrading. Compare it with the output of your COFIG dict before
# updating to the new-style config.
from pprint import pprint
from slackbridge.config.auto import load

configs = load()
CONFIG = configs.to_config_dict()
pprint(CONFIG)
