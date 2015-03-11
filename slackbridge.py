# vim: set ts=8 sw=4 sts=4 et ai:
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

  * Create at least one "Incoming WebHook" per Slack team; record the URL.
    (Pro tip: set the other relation's brand logo as default icon!)
  * Create one "Outgoing WebHook" per Slack #channel you want to join;
    record the secret "token". Set the webhook POST URL to the URL where
    this bridge is reachable from the world, and append "/outgoing" to
    the path.

Configuration of this application:

  * Set the BASE_PATH to "/". If this script does not run in the root of
    your HTTP server, you need to alter that.
  * There is a CONFIG dictionary below. You need to configure it as
    follows:

        CONFIG = {
            '<outgoing_token_from_team_1>': {
                # This one is optional. Fetch a token here:
                # https://api.slack.com/web#authentication
                'users.list': 'https://slack.com/api/users.list?token=TEAM1',
                # The next two settings are for the TEAM2-side.
                'url': '<incoming_webhook_url_from_team_2>',
                'update': {'channel': '#<name_of_shared_channel_on_team_2>'},
            },
            '<outgoing_token_from_team_2>': {
                # This one is optional.
                # https://api.slack.com/web#authentication
                'users.list': 'https://slack.com/api/users.list?token=TEAM2',
                # The next two settings are for the TEAM1-side.
                'url': '<incoming_url_from_team_1>',
                'update': {'channel': '#<name_of_shared_channel_on_team_1>'},
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
    values for the Incoming WebHook, optionally overwriting the
    #channel name.
  * The translated values get posted to the Incoming WebHook URL.

Enjoy!


Copyright (C) Walter Doekes, OSSO B.V. 2015
"""
import cgi
import datetime
import json
import logging
import re
import traceback

try:
    from urllib import request
except ImportError:
    import urllib2 as request  # python2
try:
    from urllib import parse
except ImportError:
    import urllib as parse  # python2

from multiprocessing import Process, Pipe
from pprint import pformat


# BASE_PATH needs to be set to the path prefix (location) as configured
# in the web server.
BASE_PATH = '/'
# CONFIG is a dictionary indexed by "Outgoing WebHooks" token.
# The subdictionaries contain 'url' for "Incoming WebHooks" post and
# a dictionary with payload updates ({'channel': '#new_chan'}).
# TODO: should we index it by "service_id" instead of "token"?
CONFIG = {
    'OutGoingTokenFromTeam1': {
        'url': 'https://hooks.slack.com/services/TEAM2/INCOMING/SeCrEt',
        'update': {'channel': '#shared-team2'},
    },
    'OutGoingTokenFromTeam2': {
        'url': 'https://hooks.slack.com/services/TEAM1/INCOMING/SeCrEt',
        'update': {'channel': '#shared-team1'},
    },
}

# Or, you can put the config (and logging defaults) in a separate file.
try:
    from slackbridgeconf import BASE_PATH, CONFIG
except ImportError:
    pass

# Globals initialized once below.
REQUEST_HANDLER = None
RESPONSE_WORKER = None

# # Optionally configure a basic logger.
# class Logger(logging.getLoggerClass()):
#     class AddPidFilter(logging.Filter):
#         def filter(self, record):
#             record.pid = os.getpid()
#             return True
#
#     def __init__(self, *args, **kwargs):
#         super(Logger, self).__init__(*args, **kwargs)
#         self.addFilter(Logger.AddPidFilter())
#
# log_file = '/srv/http/my.example.com/logs/%s.log' % (
#     __file__.rsplit('/', 1)[-1].rsplit('.', 1)[0],)
# logging.basicConfig(
#     filename=log_file,
#     level=logging.DEBUG,
#     format='[%(asctime)s] %(levelname)s/%(pid)s: %(message)s',
#     datefmt='%Y-%m-%d %H:%M:%S %Z')
# logging.setLoggerClass(Logger)
log = logging.getLogger('slackbridge')


class RequestHandler(object):
    def __init__(self, config, logger, ipc, base_path):
        self.config = config
        self.logger = logger
        self.ipc = ipc
        if not base_path.endswith('/'):
            base_path += '/'
        self.base_path = base_path

    def request(self, environ, start_response):
        # Single-threaded, so we can do this.
        self.env = environ
        self.start_response = start_response

        # Get all needed values.
        method = environ.get('REQUEST_METHOD')
        path_info = environ.get('PATH_INFO')
        assert (path_info == self.base_path[0:-1] or
                path_info.startswith(self.base_path)), \
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

    def respond(self, outgoingwh_values):
        # Never forward messages from the slackbot, they could cause
        # infinite loops. Especially considering that our own posted
        # messages get that exact user_id.
        if outgoingwh_values['user_id'] == 'USLACKBOT':
            log.debug('Ignoring because from slackbot: %r',
                      outgoingwh_values)
            return

        # Translate.
        token = outgoingwh_values['token']
        config = self.config.get(token)
        if not config:
            log.info('Token %s not found in config...', token)
            return
        users_list = self.get_users_list(token, config.get('users.list'))
        payload = self.outgoingwh_to_incomingwh(
            outgoingwh_values, config['update'], users_list)

        # Send.
        log.info('Responding with %r to %s', payload, config['url'])
        self.incomingwh_post(config['url'], payload)

    @classmethod
    def outgoingwh_to_incomingwh(cls, outgoingwh_values, update, users_list):
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
            'text': cls.outgoingwh_fixtext(outgoingwh_values['text'],
                                           users_list),
            'channel': '#' + outgoingwh_values['channel_name'],
            'username': outgoingwh_values['user_name'],
            'link_names': 1,
        }

        icon_url = (users_list.get(outgoingwh_values['user_id'], {})
                    .get('image_32'))
        if icon_url:
            payload.update({'icon_url': icon_url})

        payload.update(update)
        return payload

    @classmethod
    def outgoingwh_fixtext(cls, text, users_list):
        """
        Replace "abc <@U9999ZZZZ> def" with "abc @someuser def" if we
        have that user in our list.
        """
        def replace(match):
            user_id = match.groups()[0]
            try:
                return '@' + users_list[user_id]['name']
            except KeyError:
                return '<@' + user_id + '>'  # untouched
        return re.sub(r'<@(U[^>]+)>', replace, text)

    @classmethod
    def incomingwh_post(cls, url, payload):
        data = parse.urlencode({'payload': json.dumps(payload)})
        log.debug('incomingwh_post: send: %r', data)
        try:
            response = request.urlopen(url, data)
        except Exception as e:
            log.error('Posting message failed: %s', e)
            if hasattr(e, 'fp'):
                data = e.fp.read()
                log.info('Got data: %r', data)
        else:
            data = response.read()
            log.debug('incomingwh_post: recv: %r', data)

    def get_users_list(self, token, url):
        # Check if we have the list already.
        # TODO: this is now infinitely cached, not nice
        if not url:
            self.users_lists[token] = {}

        if token not in self.users_lists:
            log.info('Fetching userlist for %s...', token)
            try:
                response = request.urlopen(url)
            except Exception as e:
                log.error('Fetching userlist failed: %s', e)
                if hasattr(e, 'fp'):
                    data = e.fp.read()
                    log.info('Got data: %r', data)
                self.users_lists[token] = {}
            else:
                data = response.read()
                data = data.decode('utf-8', 'replace')
                users = json.loads(data)
                users = dict(
                    (i.get('id'),
                     {'name': i.get('name', 'NAMELESS'),
                      'image_32': i.get('profile', {}).get('image_32')})
                    for i in users.get('members', {}))
                self.users_lists[token] = users
                log.debug('users_lists: %r', self.users_lists[token])

        return self.users_lists[token]


def response_worker(config, logger, ipc):
    responsehandler = ResponseHandler(config=config, logger=logger)
    try:
        item = None
        while True:
            item = ipc.recv()
            if item is None:
                break
            elif isinstance(item, str):
                log.info('Got string: %s', item)
            else:
                try:
                    responsehandler.respond(item)
                except:
                    log.error('For item: %r', item)
                    log.error(traceback.format_exc())
                    log.warn('Continuing...')
    except:
        log.error(traceback.format_exc())
        log.warn('Aborting...')


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


# # Initialize subprocess immediately. Only use this if you use the uWSGI
# # `lazy-apps` setting or have a single worker only!
# init_globals()

if __name__ == '__main__':
    # If you don't use uWSGI, you can use the builtin_httpd.
    builtin_httpd('127.0.0.1', 8001)
