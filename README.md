slackbridge
===========

Slackbridge bridges Slack.com #channels between companies.

  * _Does your company use Slack?_
  * _Does your customer/subcontractor also use slack?_

Then, no more hard times of having to grant each others' workers access
on both Slack teams: you can now form a union between two of your Slack
\#channels using this bridge.


Configuration and setup
-----------------------

You'll need to run this as a daemon on a publicly reachable IP:

  * Test it in the foreground from the command line, to get a poor mans
    builtin http server. You can use the nginx `proxy_pass` directive
    (without path) to reach it.
  * Run it as a WSGI application. Has been tested with uWSGI; you can
    use the nginx `uwsgi_pass` directive to reach it. Multiple workers
    are allowed, as long as it is single-threaded.

Configuration in Slack:

  * Create at least one _Incoming WebHook_ per Slack team; record the URL.
    (Pro tip: set the other relation's brand logo as default icon!)
  * Create one _Outgoing WebHook_ per Slack `#channel` you want to join;
    record the secret `token`. Set the webhook POST URL to the URL where
    this bridge is reachable from the world, and append `/outgoing` to
    the path.

Configuration of this application:

  * Set the `BASE_PATH` to `"/"`. If this script does not run in the root of
    your HTTP server, you need to alter that.
  * There is a `CONFIG` dictionary below. You need to configure it as
    follows:

        CONFIG = {
            '<outgoing_token_from_team_1>': {
                # The next two settings are for the TEAM2-side.
                'iwh_url': '<incoming_webhook_url_from_team_2>',
                'iwh_update': {'channel': '#<destination_channel_on_team_2>'},
                # Linked with other, optional.
                'owh_linked': '<outgoing_token_from_team_2>',
                # Web Api token, optional, see https://api.slack.com/web.
                'wa_token': '<token_from_team1_user>',
            },
            '<outgoing_token_from_team_2>': {
                # The next two settings are for the TEAM1-side.
                'iwh_url': '<incoming_url_from_team_1>',
                'iwh_update': {'channel': '#<destination_channel_on_team_1>'},
                # Linked with other, optional.
                'owh_linked': '<outgoing_token_from_team_1>',
                # Web Api token, optional, see https://api.slack.com/web.
                'wa_token': '<token_from_team2_user>',
            },
        }

  * You can configure more pairs of bridges (or even one-way bridges) as
    needed. You can reuse the _Incoming WebHook_ URL if you want to bridge
    more channels between the same teams.

It works like this:

  * The Slack _Outgoing WebHook_ -- from both teams -- posts messages to
    the slackbridge.
  * The bridge posts the message to a subprocess, so the main process
    can return immediately.
  * The subprocess translates the values from the _Outgoing WebHook_ to
    values for the _Incoming WebHook_, optionally overwriting the
    #channel name.


TODO
----

  * Add license.
  * Clean up code (ugly globals). Too few subclasses.
  * Make more extensible. You may want to integrate your own
    slackbot-style responses here.
  * Add default icon to CONFIG, so we can reuse the same incoming
    webhook for more than one team, even if they don't supply the
    wa_token.
