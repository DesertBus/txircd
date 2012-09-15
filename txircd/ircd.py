# -*- coding: utf-8 -*-
from twisted.internet import reactor
from twisted.internet.protocol import Factory
from twisted.python import log
from twisted.words.protocols import irc
from txircd.utils import CaseInsensitiveDictionary, DefaultCaseInsensitiveDictionary
from txircd.server import IRCServer
from txircd.service import IRCService
from txircd.user import IRCUser
import uuid, time

class IRCProtocol(irc.IRC):
    UNREGISTERED_COMMANDS = ['PASS', 'USER', 'SERVICE', 'SERVER', 'NICK', 'PING', 'QUIT']

    def __init__(self, *args, **kwargs):
        self.type = None
        self.password = None
        self.nick = None

    #def get_prefix(self):
    #    # FIXME: this is bugged! irssi does not recognize stuff sent back as coming from itself
    #    return '%s!%s@%s' % (self.nick, self.username, self.transport.getHandle().getpeername()[0])

    def handleCommand(self, command, prefix, params):
        log.msg('handleCommand: %r %r %r' % (command, prefix, params))
        if not self.type and command not in self.UNREGISTERED_COMMANDS:
            return self.sendMessage(irc.ERR_NOTREGISTERED)
        elif not self.type:
            return irc.IRC.handleCommand(self, command, prefix, params)
        else:
            return self.delegateCommand(self.type, command, prefix, params)
    
    def delegateCommand(self, delegate, command, prefix, params):
        method = getattr(delegate, "irc_%s" % command, None)
        try:
            if method is not None:
                method(prefix, params)
            else:
                delegate.irc_unknown(prefix, command, params)
        except:
            log.deferr()
        

    def sendLine(self, line):
        log.msg('sendLine: %r' % line)
        return irc.IRC.sendLine(self, line)

    def irc_PASS(self, prefix, params):
        self.password = params

    def irc_NICK(self, prefix, params):
        self.nick = params

    def irc_USER(self, prefix, params):
        self.type = IRCUser(self, params, self.password, self.nick)

    def irc_SERVICE(self, prefix, params):
        self.type = IRCService(self, params, self.password)

    def irc_SERVER(self, prefix, params):
        self.type = IRCServer(self, params, self.password)

    def irc_PING(self, prefix, params):
        pass

    def irc_QUIT(self, prefix, params):
        self.loseConnection()

class IRCD(Factory):
    protocol = IRCProtocol

    def __init__(self, name, client_timeout=5 * 60, description="Welcome to TXIRCd"):
        self.name = name
        self.version = "0.1"
        self.created = time.time()
        self.token = uuid.uuid1()
        self.description = description
        self.client_timeout = client_timeout
        self.servers = CaseInsensitiveDictionary()
        self.users = CaseInsensitiveDictionary()
        self.channels = DefaultCaseInsensitiveDictionary(self.createChannel)

    def createChannel(self, name):
        return {
            "name": name,
            "mode": "",
            "topic": {
                "message": None,
                "author": "",
                "created": time.time()
            },
            "password": None,
            "limit": None,
            "users": CaseInsensitiveDictionary(),
            "bans": [],
            "exemptions": [],
            "invites": [],
            "prefixes": {
                "owner": [],
                "admin": [],
                "op": [],
                "halfop": [],
                "voice": []
            }
        }

    def broadcast(channel, message):
        for u in self.channels[channel].users.iterkeys():
            self.users[u].socket.sendLine(message)
