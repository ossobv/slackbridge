# vim: set ts=8 sw=4 sts=4 et ai:
# Slackbridge bridges Slack.com #channels between companies.
# Copyright (C) 2015,2016  Walter Doekes, OSSO B.V.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Slackbridge bridges Slack.com #channels between companies.

  * Does your company use Slack?
  * Does your customer/subcontractor also use slack?

Then, no more hard times of having to grant each others' workers access
on both Slack teams: you can now form a union between two of your Slack
#channels using this bridge.

You'll need to run this as a daemon on a publicly reachable IP:

  * Test it in the foreground from the command line, to get a poor mans
    builtin http server. You can use the nginx "proxy_pass" directive
    (without path) to reach it.
  * Run it as a WSGI application. Has been tested with uWSGI; you can
    use the nginx "uwsgi_pass" directive to reach it. Multiple workers
    are allowed, as long as it is single-threaded.

Configuration in Slack:

  * Create at least one "Incoming WebHook"[1] per Slack team; record the
    URL.
    (Pro tip: set the other relation's brand logo as default icon!)
  * Create one "Outgoing WebHook"[2] per Slack #channel you want to
    join; record the secret "token". Set the webhook POST URL to the URL
    where this bridge is reachable from the world, and append
    "/outgoing" to the path.

Configuration of this application:

  * Set the BASE_PATH to "/". If this script does not run in the root of
    your HTTP server, you need to alter that.
  * There is a CONFIG dictionary below. You need to configure it as
    follows:

        CONFIG = {
            '<outgoing_token_from_team_1>': {
                # The next two settings are for the TEAM2-side.
                'iwh_url': '<incoming_webhook_url_from_team_2>',
                'iwh_update': {'channel': '#<destination_channel_on_team_2>',
                               '_atchannel': '<team2_name_for_team1>'},
                # Linked with other, optional.
                'owh_linked': '<outgoing_token_from_team_2>',
                # Web Api token, optional, see https://api.slack.com/web.
                'wa_token': '<token_from_team1_user>',
                # Optional team 2 name to notify @team2 from team1.
                'other_name': '<team2_name>',
            },
            '<outgoing_token_from_team_2>': {
                # The next two settings are for the TEAM1-side.
                'iwh_url': '<incoming_url_from_team_1>',
                'iwh_update': {'channel': '#<destination_channel_on_team_1>',
                               '_atchannel': '<team1_name_for_team2>'},
                # Linked with other, optional.
                'owh_linked': '<outgoing_token_from_team_1>',
                # Web Api token, optional, see https://api.slack.com/web.
                'wa_token': '<token_from_team2_user>',
            },
        }

  * You can configure more pairs of bridges (or even one-way bridges) as
    needed. You can reuse the Incoming WebHook URL if you want to bridge
    more channels between the same teams.

It works like this:

  * The Slack Outgoing WebHook -- from both teams -- posts messages to
    the slackbridge.
  * The bridge posts the message to a subprocess, so the main process
    can return immediately.
  * The subprocess translates the values from the Outgoing WebHook to
    values for the Incoming WebHook:
    - It overwrites the #channel name (if 'channel' in 'iwh_update' is
      set).
    - It adds avatars to the user messages (if 'wa_token' is set).
    - It replaces @team1 with @channel (if '_atchannel' in 'iwh_update'
      is set).
    - It removes/untranslates local @mentions (if 'wa_token' is set).
  * The translated values get posted to the Incoming WebHook URL.

Supported commands by the bot -- type it in a bridged channel and get
the response there:

  * `!info` lists the users on both sides of the bridge. Now you know
    who you can @mention.


Enjoy!


[1] https://my.slack.com/services/new/incoming-webhook
[2] https://my.slack.com/services/new/outgoing-webhook

Copyright (C) Walter Doekes, OSSO B.V. 2015,2016.
License: GPLv3+
"""
import cgi
import datetime
import json
import logging
import re
import smtplib
import time
import traceback

try:
    from urllib import request
except ImportError:
    import urllib2 as request  # python2
try:
    from urllib import parse
except ImportError:
    import urllib as parse  # python2

from email.header import Header
from email.mime.text import MIMEText
from multiprocessing import Process, Pipe
from os import environ as env
from pprint import pformat


# BASE_PATH needs to be set to the path prefix (location) as configured
# in the web server.
BASE_PATH = '/'
# CONFIG is a dictionary indexed by "Outgoing WebHooks" token.
# The subdictionaries contain 'iwh_url' for "Incoming WebHooks" post and
# a dictionary with payload updates ({'channel': '#new_chan'}).
# TODO: should we index it by "service_id" instead of "(owh)token"?
try:
    CONFIG = {}
    i = 1

    while True:
        portal_config = {
            env['PORTAL_{}_SIDE_A_WEBHOOK_OUT_TOKEN'.format(i)]: {
                'iwh_url': env['PORTAL_{}_SIDE_B_WEBHOOK_IN_URL'.format(i)],
                'iwh_update': {
                    'channel': env['PORTAL_{}_SIDE_B_CHANNEL_NAME'.format(i)],
                    '_atchannel': env['PORTAL_{}_SIDE_A_GROUP_NAME'.format(i)],
                },
                'owh_linked': (
                    env['PORTAL_{}_SIDE_B_WEBHOOK_OUT_TOKEN'.format(i)]),
                'wa_token': env['PORTAL_{}_SIDE_A_WEB_API_TOKEN'.format(i)],
            },
            env['PORTAL_{}_SIDE_B_WEBHOOK_OUT_TOKEN'.format(i)]: {
                'iwh_url': env['PORTAL_{}_SIDE_A_WEBHOOK_IN_URL'.format(i)],
                'iwh_update': {
                    'channel': env['PORTAL_{}_SIDE_A_CHANNEL_NAME'.format(i)],
                    '_atchannel': env['PORTAL_{}_SIDE_B_GROUP_NAME'.format(i)],
                },
                'owh_linked': (
                    env['PORTAL_{}_SIDE_A_WEBHOOK_OUT_TOKEN'.format(i)]),
                'wa_token': env['PORTAL_{}_SIDE_B_WEB_API_TOKEN'.format(i)],
            },
        }
        CONFIG.update(portal_config)
        i += 1
except KeyError:
    pass

# Lazy initialization of workers?
LAZY_INITIALIZATION = True  # use, unless you have uwsgi-lazy-apps
# Notification settings (mail_admins) in case of broken connections.
MAIL_FROM = 'noreply@slackbridge.example.com'
MAIL_TO = ('root',)  # a tuple

# Or, you can put the config (and logging defaults) in a separate file.
try:
    from slackbridgeconf import (
        BASE_PATH, CONFIG, LAZY_INITIALIZATION, MAIL_FROM, MAIL_TO)
except ImportError:
    pass

# Globals initialized once below.
REQUEST_HANDLER = None
RESPONSE_WORKER = None

# API URLs
WA_USERS_LIST = 'https://slack.com/api/users.list?token=%(wa_token)s'
WA_CHANNELS_LIST = ('https://slack.com/api/channels.list?token=%(wa_token)s&'
                    'exclude_archived=1')

# Other
UNSET = '<unset>'

# # Optionally configure a basic logger. You'll probably want to place
# # this in the slackbridgeconf.
# class Logger(logging.getLoggerClass()):
#     class AddPidFilter(logging.Filter):
#         def filter(self, record):
#             record.pid = os.getpid()
#             return True
#
#     def __init__(self, *args, **kwargs):
#         super(Logger, self).__init__(*args, **kwargs)
#         self.addFilter(Logger.AddPidFilter())
# logging.setLoggerClass(Logger)
#
# log_file = '/srv/http/my.example.com/logs/%s.log' % (
#     __file__.rsplit('/', 1)[-1].rsplit('.', 1)[0],)
# handler = logging.handlers.RotatingFileHandler(
#     log_file, encoding='utf-8', maxBytes=(2 * 1024 * 1024), backupCount=7)
# handler.setLevel(logging.DEBUG)
# handler.setFormatter(logging.Formatter(
#     '[%(asctime)s] %(levelname)s/%(pid)s: %(message)s',
#     datefmt='%Y-%m-%d %H:%M:%S %Z'))
#
log = logging.getLogger('slackbridge')
# logger.setLevel(logging.DEBUG)
# logger.addHandler(handler)


def mail_admins(subject, body):
    msg = MIMEText(body.encode('utf-8'), 'plain', 'utf-8')
    msg['Subject'] = Header(subject.encode('utf-8'), 'utf-8')
    msg['From'] = MAIL_FROM
    msg['To'] = ', '.join(MAIL_TO)
    s = smtplib.SMTP('127.0.0.1')
    s.sendmail(MAIL_FROM, list(MAIL_TO), msg.as_string())
    s.quit()


class RequestHandler(object):
    def __init__(self, config, logger, ipc, base_path):
        self.config = config
        self.logger = logger
        self.ipc = ipc
        if base_path.endswith('/'):
            base_path = base_path[0:-1]
        self.base_path = base_path

    def request(self, environ, start_response):
        # Single-threaded, so we can do this.
        self.env = environ
        self.start_response = start_response

        # Get all needed values.
        method = environ.get('REQUEST_METHOD')
        path_info = environ.get('PATH_INFO')
        assert (path_info == self.base_path or
                path_info.startswith(self.base_path + '/')), \
            'PATH_INFO %r does not start with %r' % (path_info, self.base_path)
        self.path_info = path_info[len(self.base_path):]

        # Is it a POST or a GET?
        if method == 'GET':
            return self.get()
        elif method == 'POST':
            payload = self.get_payload(environ)
            return self.post(payload)
        else:
            start_response('405 Method Not Allowed', [('Allow', 'GET, POST')])
            return []

    def get(self):
        log.debug('Handle GET: %s', self.path_info)
        # This data tests the subprocess.
        self.ipc.send('PING @ %s: %s' %
                      (datetime.datetime.now(), self.path_info))
        # Return some debug info.
        self.start_response(
            '200 OK', [('Content-type', 'text/plain; charset=utf-8')])
        return [('Default GET:\n' + pformat(self.env)).encode('utf-8')]

    def post(self, payload):
        log.debug('Handle POST: %s, %r', self.path_info, payload)

        if self.path_info == '/outgoing':
            # Just put the entire postdata in the queue.
            # TODO: check whether the pipe is full (if posting is broken
            # for some reason)
            self.ipc.send(self.get_fields(payload))

            # Return the empty response.
            self.start_response(
                '200 OK', [('Content-type',
                            'application/json; charset=utf-8')])
            # TODO: if the pipe is full, we should reply that we cannot
            # forward anymore.
            return ['{}'.encode('utf-8')]  # don't reply to outgoing messages..

        # Unknown.
        self.start_response('404 Not Found')
        return []

    @staticmethod
    def get_payload(environ):
        # We need to read CONTENT_TYPE and REQUEST_METHOD.
        post_env = environ.copy()
        post_env['QUERY_STRING'] = ''  # we don't want GET data in there
        return cgi.FieldStorage(fp=environ['wsgi.input'], environ=post_env,
                                keep_blank_values=True)

    if hasattr(str, 'decode'):  # python2, decode data to unicode
        @staticmethod
        def get_fields(payload):
            return dict((i, payload.getfirst(i).decode('utf-8'))
                        for i in payload.keys())
    else:  # python3, already unicode
        @staticmethod
        def get_fields(payload):
            return dict((i, payload.getfirst(i)) for i in payload.keys())


class ResponseHandler(object):
    def __init__(self, config, logger):
        self.config = config
        self.log = logger
        self.users_lists = {}
        self.channels_lists = {}

    def respond(self, outgoingwh_values):
        # Never forward messages from the slackbot, they could cause
        # infinite loops. Especially considering that our own posted
        # messages get that exact user_id.
        if outgoingwh_values['user_id'] == 'USLACKBOT':
            self.log.debug('Ignoring because from slackbot: %r',
                           outgoingwh_values)
            return

        # Translate.
        owh_token = outgoingwh_values['token']
        config = self.config.get(owh_token)
        if not config:
            self.log.info('OWH token %s not found in config...', owh_token)
            return

        # Exceptions to regular forwarding.
        if outgoingwh_values['text'] == '!info':
            # Fetch info, and send to local channel only.
            info = self.get_info(owh_token)
            try:
                remote_config = self.config[config['owh_linked']]
                remote_iwh_url = remote_config['iwh_url']
            except KeyError:
                self.log.warn('Could not get linked IWH URL')
                return
            payload = {
                'text': '(local reply only)\n' + '\n'.join(
                    '@%s %s: %s' % (
                        i['atchannel'], i['channel'],
                        ', '.join(sorted(i['users'])))
                    for i in sorted(info.values(),
                                    key=(lambda x: x['channel']))),
                'channel': '#' + outgoingwh_values['channel_name']
            }
            # Send.
            self.log.info('Responding with %r to %s', payload, remote_iwh_url)
            self.incomingwh_post(remote_iwh_url, payload)
            return

        users_list = self.get_users_list(
            owh_token, config.get('wa_token'))
        channels_list = self.get_channels_list(
            owh_token, config.get('wa_token'))
        payload = self.outgoingwh_to_incomingwh(
            outgoingwh_values, config['iwh_update'], users_list, channels_list)

        # Send.
        self.log.info('Responding with %r to %s', payload, config['iwh_url'])
        self.incomingwh_post(config['iwh_url'], payload)

    @classmethod
    def outgoingwh_to_incomingwh(cls, outgoingwh_values, update,
                                 users_list, channels_list):
        # https://api.slack.com/docs/formatting
        #
        # {'user_id': 'USLACKBOT', 'channel_name': 'crack', 'timestamp':
        # '1425548120.000032', 'team_id': 'T9999ZZZZ', 'channel_id':
        # 'C9999ZZZZ', 'token': 'OutGoingTokenFromTeam1', 'text':
        # 'I used to work at Kwik-Fit, but I gave up the job; every day '
        # 'I was tyred and exhausted.', 'team_domain': 'ossobv',
        # 'user_name': 'slackbot', 'service_id': '1234567890'}
        #
        # For unknown users we get:
        #   "ja volgens mij ook @walter"
        # When written to incoming (with link_names=1), this translates
        # to:
        #   "ja volgens mij ook <@U9999ZZZZ|walter>"
        # that is, including magic angle brackets.
        #
        # Link-names also translates @channel:
        #   "@channel: sorry voor de test spam"
        # becomes:
        #   "<!channel>: sorry voor de test spam"
        #
        # Literal angle brackets are already escaped before being passed
        # to us:
        #   "test &lt;@wdoekes&gt; 1..2..3" and
        #   "icon voor je incoming webhook: <https://s..._48.jpg>"
        # So that can be safely forwarded without requiring additional
        # escaping.
        #
        # In conclusion, since we don't know the U-number of the remote
        # users, we won't use parse=none, but will use link_names=1.
        #
        payload = {
            'text': cls.outgoingwh_fixtext(
                outgoingwh_values['text'],
                users_list, channels_list,
                atchannel=update.get('_atchannel')),
            'channel': '#' + outgoingwh_values['channel_name'],
            'username': outgoingwh_values['user_name'],
            'link_names': 1,
        }

        icon_url = (users_list.get(outgoingwh_values['user_id'], {})
                    .get('image_32'))
        if icon_url:
            payload.update({'icon_url': icon_url})

        payload.update(
            dict((k, v) for k, v in update.items() if not k.startswith('_')))
        return payload

    @classmethod
    def outgoingwh_fixtext(cls, text, users_list, channels_list, atchannel):
        """
        Replace "abc <@U9999ZZZZ> def" with "abc @someuser def" if we
        have that user in our list.

        Replace "@teamname" with "@channel" if teamname is defined.

        Replace "abc <#C03CYDD1R> def" with "abc #somechan def" if we have that
        channel in our list.
        """
        def replace_channel(match):
            channel_id = match.groups()[0]
            try:
                return '#' + channels_list[channel_id]['name']
            except KeyError:
                return '<#' + channel_id + '>'  # untouched

        def replace_user(match):
            user_id = match.groups()[0]
            try:
                return '@' + users_list[user_id]['name']
            except KeyError:
                return '<@' + user_id + '>'  # untouched

        # @teamname => @channel
        if atchannel:
            text = re.sub(r'(^|[^\w])@' + atchannel + r'\b',
                          r'\1@channel',
                          text,
                          flags=re.I)

        # <@U123> => @user
        text = re.sub(r'<@(U[^>]+)>', replace_user, text)

        # <#C123> => #channel
        text = re.sub(r'<#(C[^>]+)>', replace_channel, text)

        return text

    @classmethod
    def incomingwh_post(cls, url, payload):
        data = parse.urlencode({'payload': json.dumps(payload)})
        log.debug('incomingwh_post: send: %r', data)

        tries = 5
        for i in range(tries):
            try:
                response = request.urlopen(url, data.encode('utf-8'))
            except Exception as e:
                log.error('Posting message (try %d) failed: %s', i, e)
                if hasattr(e, 'fp'):
                    ret = e.fp.read()
                    log.info('Got data: %r', ret)

                if i < (tries - 1):
                    time.sleep(3 * i + 1)
                else:
                    log.error('Posting message failed completely: %s', e)
                    mail_admins(
                        'Slack message posting failed: %s' % (e,),
                        '%r\n%r\nMessage could not be delivered' % (e, ret))
            else:
                data = response.read()
                log.debug('incomingwh_post: recv: %r', data)
                break

    def get_users_list(self, owh_token, wa_token):
        # Check if we have the list already.
        # TODO: this is now infinitely cached, not nice
        if not wa_token:
            self.users_lists[owh_token] = {}

        if owh_token not in self.users_lists:
            self.log.info('Fetching users.list for %s...', owh_token)
            url = WA_USERS_LIST % {'wa_token': wa_token}
            try:
                response = request.urlopen(url)
            except Exception as e:
                self.log.error('Fetching users.list failed: %s', e)
                if hasattr(e, 'fp'):
                    data = e.fp.read()
                    self.log.info('Got data: %r', data)
                self.users_lists[owh_token] = {}
            else:
                data = response.read()
                data = data.decode('utf-8', 'replace')
                users = json.loads(data)
                users = dict(
                    (i.get('id'),
                     {'name': i.get('name', UNSET),
                      'image_32': i.get('profile', {}).get('image_32')})
                    for i in users.get('members', []))
                self.users_lists[owh_token] = users
                self.log.debug('users_lists: %r', self.users_lists[owh_token])

        return self.users_lists[owh_token]

    def get_channels_list(self, owh_token, wa_token):
        # Check if we have the list already.
        # TODO: this is now infinitely cached, not nice
        if not wa_token:
            self.channels_lists[owh_token] = {}

        if owh_token not in self.channels_lists:
            self.log.info('Fetching channels.list for %s...', owh_token)
            url = WA_CHANNELS_LIST % {'wa_token': wa_token}
            try:
                response = request.urlopen(url)
            except Exception as e:
                self.log.error('Fetching channels.list failed: %s', e)
                if hasattr(e, 'fp'):
                    data = e.fp.read()
                    self.log.info('Got data: %r', data)
                self.channels_lists[owh_token] = {}
            else:
                data = response.read()
                data = data.decode('utf-8', 'replace')
                channels = json.loads(data)
                channels = dict(
                    (i.get('id'),
                     {'name': i.get('name', UNSET)})
                    for i in channels.get('channels', []))
                self.channels_lists[owh_token] = channels
                self.log.debug(
                    'channels_lists: %r', self.channels_lists[owh_token])

        return self.channels_lists[owh_token]

    def get_channel_members(self, wa_token, channel_name):
        """
        We could get the channel info from the ``channel.info`` call,
        but then we need the channel id (C9999ZZZZ), which we don't
        have.
        """
        self.log.info('Fetching channels.list for %s...', channel_name)
        url = WA_CHANNELS_LIST % {'wa_token': wa_token}
        try:
            response = request.urlopen(url)
        except Exception as e:
            self.log.error('Fetching channels.list failed: %s', e)
            if hasattr(e, 'fp'):
                data = e.fp.read()
                self.log.info('Got data: %r', data)
        else:
            data = response.read()
            data = data.decode('utf-8', 'replace')
            channels = json.loads(data)
            self.log.debug('channels.list: %r', channels)
            for channel in channels.get('channels', []):
                if channel.get('name') == channel_name:
                    return channel.get('members', [])
        return []

    def get_channel_users(self, owh_token, wa_token, channel_name):
        members = self.get_channel_members(wa_token, channel_name)
        if not members:
            return members

        users_list = self.get_users_list(owh_token, wa_token)
        return [users_list.get(i, {'name': i})['name'] for i in members]

    def get_info(self, local_owh_token):
        # Get info about channel linkage and local and remote users.
        local_config = self.config[local_owh_token]
        local_channel = remote_channel = UNSET
        local_atchannel = remote_atchannel = UNSET
        local_users = remote_users = []
        local_wa_token = local_config.get('wa_token', '')

        remote_owh_token = local_config.get('owh_linked')
        remote_config = self.config.get(remote_owh_token, {})
        remote_wa_token = remote_config.get('wa_token', '')

        try:
            if local_config['iwh_update']['channel'][0:1] == '#':
                remote_channel = local_config['iwh_update']['channel'][1:]
            elif remote_config:
                # Lookup channel name from channel id.
                channels_list = self.get_channels_list(
                    remote_owh_token, remote_wa_token)
                tmp_channel = channels_list.get(
                    local_config['iwh_update']['channel'])
                if tmp_channel:
                    remote_channel = tmp_channel['name']
        except KeyError:
            pass

        try:
            remote_atchannel = local_config['iwh_update']['_atchannel']
        except KeyError:
            pass

        if remote_config:
            try:
                if remote_config['iwh_update']['channel'][0:1] == '#':
                    local_channel = remote_config['iwh_update']['channel'][1:]
                else:
                    # Lookup channel name from channel id.
                    channels_list = self.get_channels_list(
                        local_owh_token, local_wa_token)
                    tmp_channel = channels_list.get(
                        remote_config['iwh_update']['channel'])
                    if tmp_channel:
                        local_channel = tmp_channel['name']
            except KeyError:
                pass
            try:
                local_atchannel = remote_config['iwh_update']['_atchannel']
            except KeyError:
                pass

        if local_channel and local_wa_token:
            local_users = self.get_channel_users(
                local_owh_token, local_wa_token, local_channel)
        if remote_channel and remote_wa_token:
            remote_users = self.get_channel_users(
                remote_owh_token, remote_wa_token, remote_channel)

        return {
            local_owh_token: {'channel': '#' + local_channel,
                              'users': local_users,
                              'atchannel': local_atchannel},
            remote_owh_token: {'channel': '#' + remote_channel,
                               'users': remote_users,
                               'atchannel': remote_atchannel},
        }

    # def test(self, owh_token):
    #     x = self.get_info(owh_token)
    #     self.log.debug('TEST: %r', x)


def response_worker(config, logger, ipc):
    responsehandler = ResponseHandler(config=config, logger=logger)
    try:
        item = None
        while True:
            item = ipc.recv()
            if item is None:
                break
            elif isinstance(item, str):
                logger.info('Got string: %s', item)
                # if item.rsplit('/', 1)[-1] in config:
                #     responsehandler.test(item.rsplit('/', 1)[-1])
            else:
                try:
                    responsehandler.respond(item)
                except:
                    logger.error('For item: %r', item)
                    logger.error(traceback.format_exc())
                    logger.warn('Continuing...')
    except:
        logger.error(traceback.format_exc())
        logger.warn('Aborting...')


def application(environ, start_response):
    global REQUEST_HANDLER
    if not REQUEST_HANDLER:
        # Lazily initialize the subprocess. If you don't use the uWSGI
        # `lazy-apps` setting, you need it to be done on the first request.
        # Note that that seems to cause a response issue (with nginx) for the
        # first request.
        init_globals()

    # log.debug('Got request:\n%r', environ)
    return REQUEST_HANDLER.request(environ, start_response)


def init_globals():
    global REQUEST_HANDLER, RESPONSE_WORKER

    log.info('Starting workers...')
    # For some reason, using a Queue() did not work at all as soon
    # as this was started from uWSGI. In buildin_httpd mode it
    # worked fine. But in uWSGI the Queue seemed to buffer outgoing
    # messages.
    parent_pipe, child_pipe = Pipe()
    RESPONSE_WORKER = Process(
        target=response_worker, args=(CONFIG, log, child_pipe))
    RESPONSE_WORKER.start()
    REQUEST_HANDLER = RequestHandler(
        config=CONFIG, logger=log, ipc=parent_pipe, base_path=BASE_PATH)

    # Add handler to shutdown gracefully from uWSGI. This is needed
    # for graceful uWSGI reload/shutdown.
    try:
        import uwsgi
    except ImportError:
        pass
    else:
        def goodbye():
            log.debug('Stopping workers...')
            REQUEST_HANDLER.ipc.send(None)  # HAXX
            RESPONSE_WORKER.join()
            log.info('Finished...')
        uwsgi.atexit = goodbye


def builtin_httpd(address, port):
    from wsgiref.simple_server import make_server
    log.info('Starting builtin httpd...')
    server = make_server(address, port, application)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        if RESPONSE_WORKER:
            log.debug('Stopping workers...')
            REQUEST_HANDLER.ipc.send(None)  # HAXX
            RESPONSE_WORKER.join()
        log.info('Finished...')


# Initialize subprocess immediately. Only use this if you use the uWSGI
# `lazy-apps` setting or have a single worker only!
if not LAZY_INITIALIZATION:
    init_globals()


if __name__ == '__main__':
    # If you don't use uWSGI, you can use the builtin_httpd.
    builtin_httpd('127.0.0.1', 8001)
