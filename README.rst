##################
Twisted IRC Daemon
##################

Not much here yet, move along.

If you wanna hack around with it do the following:

* Clone the repo
* Make a virtualenv
* Install the requirements (``pip install -r requirements.txt`` after virtualenv activation)
* Run ``python app.py`` (Use ``-h`` for help)
* Connect to the IRC Daemon

###############
OPER privileges
###############

Current
=======

* Can't be kicked for sending too much data
* Can't be shunned
* Can't be x:lined
* Can join a password'd channel without the password
* Can join a limit'd channel at its limit
* Can join an invite-only channel without an invite
* Can join a channel they are banned in
* Can talk in a channel while banned
* Can view/change modes of other users
* Can change channel modes without HOP
* Can set channel topic without HOP
* Can kick anyone out of a channel
* Sees IP address of user on WHOIS (instead of hostname)
* Sees IP address of user on WHOWAS (instead of hostname)
* Can KILL users
* Can x:line/shun users
* Can REHASH config file
* Can make the server DIE (if set as such in the config file)
* Can make the server RESTART (if set as such in the config file)
* Can set channel modes without being in the channel
* Can set channel modes without being proper level
* Can remove channel modes without being proper level
* Can't have channel modes removed from them
* Can kick somebody from a channel without being in channel

Proposed Additions
==================

* Can talk in a moderated channel
* Can talk to a channel they aren't in
* Can use colors in a stripped channel
* Can bypass flood limit in a channel
* Can set channel topic without being in channel
* See IP address of user on JOIN (instead of hostname)
* See all channels with LIST
* Invite someone to a channel without being on the channel, or without being a HOP
