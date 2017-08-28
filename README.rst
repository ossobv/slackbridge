SlackBridge
===========

SlackBridge bridges Slack.com #channels between companies.

* *Does your company use Slack?*
* *Does your customer/subcontractor also use slack?*

Then, no more hard times of having to grant each others' workers access
on both Slack teams: you can now form a union between two of your Slack
#channels using this bridge.


Configuration and setup
-----------------------

You'll need to run this as a daemon on a publicly reachable IP:

* Test it in the foreground from the command line, to get a poor mans
  builtin http server. You can use the nginx ``proxy_pass`` directive
  (without path) to reach it.
* Run it as a WSGI application. Has been tested with uWSGI; you can
  use the nginx ``uwsgi_pass`` directive to reach it. Multiple workers
  are allowed, as long as it is single-threaded.

Configuration in Slack:
~~~~~~~~~~~~~~~~~~~~~~~

* Create at least one `Incoming WebHook
  <https://my.slack.com/services/new/incoming-webhook>`_ per Slack
  team; record *the URL*.
  (Tip: set the other relation's brand logo as default icon, or a
  generic ``:speech_balloon:`` icon if you use it for multiple
  channels.)
* For *each* #channel that you want to bridge/share, create an
  `Outgoing WebHook
  <https://my.slack.com/services/new/outgoing-webhook>`_, record the
  *token*. Set the WebHook POST URL to where this bridge is reachable
  from the world, and append ``/outgoing`` to the path.
* And, preferably, you'll also need at least one WebAPI token to
  supply some info to the other end. You can do this by `creating a
  bot user <https://my.slack.com/services/new/bot>`_ (call it
  *@slackbridge*). Record the *API token*.
  (Previously, the recommended token was a "user token", which is now
  `legacy <https://api.slack.com/custom-integrations/legacy-tokens>`_.)

Inifile configuration:
~~~~~~~~~~~~~~~~~~~~~~

Configuration using an inifile would look like this (skip if you're
using Heroku)::

    [yourcompany-othercompany]
    A.webhook_out_token = <the-recorded-token>
    A.webhook_in_url = <the-recorded-url>
    A.channel = #<channel-you-wish-to-share>
    A.peername = othercompany
    A.webapi_token = <xoxb-bot-token-goes-here>

The other side of the SlackBridge has to do the same "Configuration in
Slack" steps as seen above. Those values should go into a second set of
key-value pairs, starting with ``B``::

    B.webhook_out_token = <the-peers-recorded-token>
    B.webhook_in_url = <the-peers-recorded-url>
    B.channel = #<channel-they-wish-to-share>
    B.peername = yourcompany
    B.webapi_token = <xoxb-their-bot-token-goes-here>

The inifile will be searched as ``./slackbridge.ini`` or in the location
supplied by the ``SLACKBRIDGE_INIFILE`` environment variable.

You can add extra sections for more bridges. See the ``sample.ini``
example configuration for more details.

Environment variable (Heroku style) configuration:
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Instead of doing inifile config, you can use environment variables.

In that case, instead of the ``A`` and ``B`` config as seen above, you'd
set these for both ``A`` and ``B``::

    PORTAL_1_SIDE_A_WEBHOOK_OUT_TOKEN=
    PORTAL_1_SIDE_A_WEBHOOK_IN_URL=
    PORTAL_1_SIDE_A_CHANNEL_NAME=
    PORTAL_1_SIDE_A_GROUP_NAME=
    PORTAL_1_SIDE_A_WEB_API_TOKEN=

You can increment the number ``1`` for more bridges. See the
``sample.env`` example configuration for more details.


Inner workings
--------------

The SlackBridge works like this:

* The Slack *Outgoing WebHook* -- from both teams -- posts messages to
  the slackbridge on the supplied ``/outgoing`` URL.
* The bridge posts the message to a subprocess, so the main process
  can return immediately.
* The subprocess translates the values from the *Outgoing WebHook* to
  values for the *Incoming WebHook*, optionally overwriting the
  #channel name and some other translations (channel name, avatars,
  @mentions).
* The translated values get posted to the *Incoming WebHook URL* so
  they end up on the other end of the bridge.

Supported commands by the bot -- type it in a bridged channel and get
the response there:

* ``!info`` lists the users on both sides of the bridge. Now you know
  who you can @mention.


Heroku
------

These instructions require `Heroku Command Line
<https://devcenter.heroku.com/articles/heroku-command-line>`_::

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

Things to note:

* Free Heroku dynos can only run 18 hours per day. After that, the
  slack bridge will simply not work. This can be very confusing. You
  may wish to consider paying $7/month for a 24h dyno.
* Please see ``sample.env`` for an example of how to set environment
  variables.


BUGS / CAVEATS
--------------

* You can skip the WebAPI token, but @mentions will look awkward and
  ``!info`` won't give you all the info.
* Message edits and snippet/file/image uploads will not get sent
  across the bridge.


TODO
----

* Clean up code (ugly globals). Too few subclasses.
* Make more extensible. You may want to integrate your own
  slackbot-style responses here.
* Add default icon to CONFIG, so we can reuse the same incoming
  webhook for more than one team, even if they don't supply the
  wa_token.
* Clean up the config. It's a horrible mess as it is.
