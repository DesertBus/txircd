# -*- coding: utf-8 -*-
import time
from collections import defaultdict
from functools import partial
from twisted.internet import reactor
from twisted.internet.protocol import Factory
from twisted.python import log
from twisted.words.protocols import irc
from .utils import parse_args, multi, iterate_non_blocking


class IRCProtocol(irc.IRC):
    UNREGISTERED_COMMANDS = ['PASS', 'USER', 'NICK', 'PING', 'QUIT']
    REGISTERED_ATTRIBUTES = ['nick', 'username', 'hostname', 'servername', 'realname']

    def __init__(self, *args, **kwargs):
        self.nick = None
        self.username = None
        self.hostname = None
        self.servername = None
        self.realname = None
        self.sign_on = time.time()
        self.last_msg = time.time()
        self.channels = []

    def initiate_timeout(self):
        self.timeout = reactor.callLater(self.ircd.client_timeout, self.handle_timeouts)

    def handle_timeouts(self):
        if self.nick:
            self.ircd.quit(self)
            self.sendMessage('KILL', 'Timeout')
            self.transport.loseConnection()

    def is_registered(self):
        getfromself = partial(getattr, self)
        return all(map(getfromself, self.REGISTERED_ATTRIBUTES))

    def check_registration(self):
        if self.is_registered():
            if self.ircd.join_server(self):
                log.msg("User %r joined server, %s users on server" % (self.nick, len(self.ircd.users)))
                self.sendMessage('MODE')

    def handleCommand(self, command, prefix, params):
        log.msg('handleCommand: %r %r %r' % (command, prefix, params))
        self.timeout.reset(self.ircd.client_timeout)
        if not self.is_registered() and command not in self.UNREGISTERED_COMMANDS:
            return self.sendMessage(irc.ERR_NOTREGISTERED)
        else:
            return irc.IRC.handleCommand(self, command, prefix, params)

    def sendLine(self, line):
        log.msg('sendLine: %r' % line)
        return irc.IRC.sendLine(self, line)

    def irc_unknown(self, command, params):
        pass

    @parse_args
    def irc_USER(self, username, hostname, servername, realname):
        self.sendLine(irc.RPL_WELCOME)
        self.username = username
        self.hostname = hostname
        self.servername = servername
        self.realname = realname
        self.check_registration()

    @parse_args
    def irc_NICK(self, nickname=None, hopcount=None):
        log.msg("NICK: %r %r" % (nickname, hopcount))
        if not nickname:
            return self.sendMessage(irc.ERR_NONICKNAMEGIVEN)
        elif nickname in self.ircd.users:
            return self.sendMessage(irc.ERR_NICKNAMEINUSE)
        if self.nick:
            self.ircd.rename(self.nick, nickname)
        self.nick = nickname
        self.check_registration()

    @parse_args
    def irc_PRIVMSG(self, targets, message):
        self.last_msg = time.time()

        def itr():
            for target in targets.split(','):
                for _ in self.ircd.privmsg(self.nick, target, message):
                    yield

        iterate_non_blocking(itr())

    @parse_args
    def irc_PING(self, *servers):
        self.sendLine('PONG')

    @parse_args
    def irc_MODE(self, *args):
        pass

    def server_WHOIS(self, server, nicknames):
        log.msg("server_WHOIS %r %r" % (server, nicknames))

    def user_WHOIS(self, nicknames):
        log.msg("user_WHOIS %r" % nicknames)
        def itr():
            for nickname in nicknames.split(','):
                client = self.ircd.get_client(nickname)
                if client is None:
                    self.sendMessage(irc.ERR_NOSUCHNICK)
                else:
                    self.whois(self.nick, client.nick, client.username, client.hostname, client.realname, 'localhost',
                        'localhost', False, time.time() - client.last_msg, client.sign_on, client.channels)
                yield
        iterate_non_blocking(itr())

    irc_WHOIS = multi('irc_WHOIS', server_WHOIS, user_WHOIS)

    @parse_args
    def irc_JOIN(self, channel, keys=None):
        self.channels.append(channel)
        self.ircd.join_channel(self, channel)
        self.sendMessage(irc.RPL_TOPIC, "No topic")

    @parse_args
    def irc_QUIT(self, message):
        if self.nick:
            self.ircd.leave_server(self)


class IRCD(Factory):
    protocol = IRCProtocol

    def __init__(self, client_timeout=5 * 60):
        self.client_timeout = client_timeout
        self.channels = defaultdict(list)
        self.users = {}

    def get_client(self, nick):
        return self.users.get(nick, None)

    def join_channel(self, client, channel):
        if client not in self.channels[channel]:
            self.channels[channel].append(client)
            log.msg("%s joined channel %s, %s users in channel" % (client.nick, channel, len(self.channels[channel])))

    def leave_channel(self, client, channel):
        if client in self.channels[channel]:
            self.channels[channel].remove(client.nick)
        if channel in self.users[client.nick]:
            self.users[client.nick]['channels'].remove(channel)

    def join_server(self, client):
        if client.nick in self.users:
            return False
        self.users[client.nick] = client
        return True

    def leave_server(self, client):
        for channel in client.channels:
            if client in self.channels[channel]:
                self.channels[channel].remove(client)
        if client.nick in self.users:
            del self.users[client.nick]
        log.msg("User %r quit server, %s on server" % (client.nick, len(self.users)))

    def privmsg(self, sender, target, message):
        if target.startswith('#'):
            for client in self.channels[target]:
                if client == sender:
                    continue
                client.privmsg(sender, target, message)
                yield
        else:
            client = self.users.get(target, None)
            if client:
                client.privmsg(sender, target, message)
            yield

    def rename(self, old, new):
        if old in self.users:
            self.users[new] = self.users.pop(old)

    def buildProtocol(self, addr):
        proto = Factory.buildProtocol(self, addr)
        proto.ircd = self
        proto.initiate_timeout()
        return proto
