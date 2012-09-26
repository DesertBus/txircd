# -*- coding: utf-8 -*-
from twisted.internet import reactor
from twisted.internet.protocol import Factory
from twisted.python import log
from twisted.words.protocols import irc
from txircd.utils import CaseInsensitiveDictionary, DefaultCaseInsensitiveDictionary, VALID_USERNAME
from txircd.mode import ChannelModes
from txircd.server import IRCServer
from txircd.service import IRCService
from txircd.user import IRCUser
import uuid, time, socket

irc.RPL_CREATIONTIME = '329'

class IRCProtocol(irc.IRC):
    UNREGISTERED_COMMANDS = ['PASS', 'USER', 'SERVICE', 'SERVER', 'NICK', 'PING', 'QUIT']

    def __init__(self, *args, **kwargs):
        self.type = None
        self.password = None
        self.nick = None
        self.user = None

    def handleCommand(self, command, prefix, params):
        log.msg('handleCommand: %r %r %r' % (command, prefix, params))
        if not self.type and command not in self.UNREGISTERED_COMMANDS:
            return self.sendMessage(irc.ERR_NOTREGISTERED, "%s :You have not registered" % command, prefix=self.hostname)
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
        if not params:
            return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "PASS :Not enough parameters", prefix=self.hostname)
        self.password = params

    def irc_NICK(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.hostname)
        elif params[0] in self.factory.users:
            self.sendMessage(irc.ERR_NICKNAMEINUSE, "%s :Nickname is already in use" % params[0], prefix=self.hostname)
        elif not VALID_USERNAME.match(params[0]):
            self.sendMessage(irc.ERR_ERRONEUSNICKNAME, "%s :Erroneous nickname" % params[0], prefix=self.hostname)
        else:
            self.nick = params[0]
            if self.user:
                self.type = IRCUser(self, self.user, self.password, self.nick)

    def irc_USER(self, prefix, params):
        if len(params) < 4:
            return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER :Not enough parameters", prefix=self.hostname)
        self.user = params
        if self.nick:
            self.type = self.factory.types['user'](self, self.user, self.password, self.nick)

    def irc_SERVICE(self, prefix, params):
        self.type = self.factory.types['service'](self, params, self.password)

    def irc_SERVER(self, prefix, params):
        self.type = self.factory.types['server'](self, params, self.password)

    def irc_PING(self, prefix, params):
        if params:
            self.sendMessage("PONG", "%s :%s" % (self.factory.hostname, params[0]), prefix=self.factory.hostname)
        else:
            self.sendMessage(irc.ERR_NOORIGIN, "%s :No origin specified" % self.nickname, prefix=self.factory.hostname)

    def irc_QUIT(self, prefix, params):
        self.transport.loseConnection()
        
    def connectionLost(self, reason):
        if self.type:
            self.type.connectionLost(reason)

class IRCD(Factory):
    protocol = IRCProtocol
    channel_prefixes = "#"
    oper_hosts = ["127.0.0.1","129.161.209.91"]
    opers = {"Fugiman":"test"}
    types = {
        'user': IRCUser,
        'server': IRCServer,
        'service': IRCService,
    }
    prefix_order = "qaohv" # Hardcoded into modes :(
    prefix_symbols = {
        'q': '~',
        'a': '&',
        'o': '@',
        'h': '%',
        'v': '+'
    }

    def __init__(self, name, client_timeout=5 * 60, description="Welcome to TXIRCd"):
        self.name = name
        self.hostname = socket.getfqdn()
        self.version = "0.1"
        self.created = time.time()
        self.token = uuid.uuid1()
        self.description = description
        self.client_timeout = client_timeout
        self.servers = CaseInsensitiveDictionary()
        self.users = CaseInsensitiveDictionary()
        self.channels = DefaultCaseInsensitiveDictionary(self.createChannel)

    def buildProtocol(self, addr):
        p = Factory.buildProtocol(self, addr)
        p.hostname = self.hostname
        return p
    
    def createChannel(self, name):
        c = {
            "name": name,
            "created": time.time(),
            "topic": {
                "message": None,
                "author": "",
                "created": time.time()
            },
            "users": CaseInsensitiveDictionary(),
        }
        c["mode"] = ChannelModes(self, c, "nt", name)
        return c
