slackbridge
===========

Slackbridge bridges Slack.com #channels between companies.

  * _Does your company use Slack?_
  * _Does your customer/subcontractor also use slack?_

Then, no more hard times of having to grant each others' workers access
on both Slack teams: you can now form a union between two of your Slack
\#channels using this bridge.

**Note:** This fork has been customized to work on Heroku. (See below
section.)


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

  * Create at least one
    [Incoming WebHook](https://my.slack.com/services/new/incoming-webhook)
    per Slack team; record the URL.
    (Pro tip: set the other relation's brand logo as default icon!)
  * Create one
    [Outgoing WebHook](https://my.slack.com/services/new/outgoing-webhook)
    _per_ Slack `#channel` you want to join;
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
                'iwh_update': {'channel': '#<destination_channel_on_team_2>',
                               '_atchannel': '<team2_name_for_team1>'},
                # Linked with other, optional.
                'owh_linked': '<outgoing_token_from_team_2>',
                # Web Api token, optional, see https://api.slack.com/web.
                'wa_token': '<token_from_team1_user>',
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
  * The subprocess translates the values from the _Outgoing WebHook_ to
    values for the Incoming WebHook:
    - It overwrites the #channel name (if `channel` in `iwh_update` is
      set).
    - It adds avatars to the user messages (if `wa_token` is set).
    - It replaces @team1 with @channel (if `_atchannel` in `iwh_update`
      is set).
    - It removes/untranslates local @mentions (if `wa_token` is set).
  * The translated values get posted to the Incoming WebHook URL.

Supported commands by the bot -- type it in a bridged channel and get
the response there:

  * `!info` lists the users on both sides of the bridge. Now you know
    who you can @mention.


Heroku
------

This fork is customized to work on Heroku. These instructions require
[Heroku Command
Line](https://devcenter.heroku.com/articles/heroku-command-line).

```
heroku create
cp sample.env .env
# Properly set all environment variables in file
vim .env
# Test running the bridge locally
heroku local
# Push environment variables to Heroku
heroku config:push --overwrite
# Deploy to Heroku
git push heroku <my-branch>
```


TODO
----

  * Clean up code (ugly globals). Too few subclasses.
  * Make more extensible. You may want to integrate your own
    slackbot-style responses here.
  * Add default icon to CONFIG, so we can reuse the same incoming
    webhook for more than one team, even if they don't supply the
    wa_token.
  * Clean up the config. It's a horrible mess as it is.
