# -*- coding: utf-8 -*-
from twisted.internet import reactor
from twisted.internet.protocol import Factory
from twisted.python import log
from twisted.words.protocols import irc
from txircd.utils import CaseInsensitiveDictionary, DefaultCaseInsensitiveDictionary, VALID_USERNAME, now
from txircd.mode import ChannelModes
from txircd.server import IRCServer
from txircd.service import IRCService
from txircd.user import IRCUser
import uuid, socket, collections

irc.RPL_CREATIONTIME = "329"
irc.RPL_TOPICWHOTIME = "333"

Channel = collections.namedtuple("Channel",["name","created","topic","users","mode"])

class IRCProtocol(irc.IRC):
    UNREGISTERED_COMMANDS = ["PASS", "USER", "SERVICE", "SERVER", "NICK", "PING", "QUIT"]

    def __init__(self, *args, **kwargs):
        self.type = None
        self.password = None
        self.nick = None
        self.user = None

    def handleCommand(self, command, prefix, params):
        log.msg("handleCommand: {!r} {!r} {!r}".format(command, prefix, params))
        if not self.type and command not in self.UNREGISTERED_COMMANDS:
            return self.sendMessage(irc.ERR_NOTREGISTERED, command, ":You have not registered", prefix=self.hostname)
        elif not self.type:
            return irc.IRC.handleCommand(self, command, prefix, params)
        else:
            return self.delegateCommand(self.type, command, prefix, params)
    
    def delegateCommand(self, delegate, command, prefix, params):
        method = getattr(delegate, "irc_{}".format(command), None)
        try:
            if method is not None:
                method(prefix, params)
            else:
                delegate.irc_unknown(prefix, command, params)
        except:
            log.deferr()
        

    def sendLine(self, line):
        log.msg("sendLine: {!r}".format(line))
        return irc.IRC.sendLine(self, line)

    def irc_PASS(self, prefix, params):
        if not params:
            return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "PASS", ":Not enough parameters", prefix=self.hostname)
        self.password = params

    def irc_NICK(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.hostname)
        elif not VALID_USERNAME.match(params[0]):
            self.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname", prefix=self.hostname)
        elif params[0] in self.factory.users:
            self.sendMessage(irc.ERR_NICKNAMEINUSE, self.factory.users[params[0]].nickname, ":Nickname is already in use", prefix=self.hostname)
        else:
            self.nick = params[0]
            if self.user:
                try:
                    self.type = IRCUser(self, self.user, self.password, self.nick)
                except ValueError:
                    self.type = None
                    self.transport.loseConnection()

    def irc_USER(self, prefix, params):
        if len(params) < 4:
            return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Not enough parameters", prefix=self.hostname)
        self.user = params
        if self.nick:
            try:
                self.type = self.factory.types["user"](self, self.user, self.password, self.nick)
            except ValueError:
                self.type = None
                self.transport.loseConnection()

    def irc_SERVICE(self, prefix, params):
        try:
            self.type = self.factory.types["service"](self, params, self.password)
        except ValueError:
            self.type = None
            self.transport.loseConnection()

    def irc_SERVER(self, prefix, params):
        try:
            self.type = self.factory.types["server"](self, params, self.password)
        except ValueError:
            self.type = None
            self.transport.loseConnection()

    def irc_PING(self, prefix, params):
        if params:
            self.sendMessage("PONG", self.factory.hostname, ":{}".format(params[0]), prefix=self.factory.hostname)
        else: # TODO: There's no nickname here, what do?
            self.sendMessage(irc.ERR_NOORIGIN, "CHANGE_THIS", ":No origin specified", prefix=self.factory.hostname)

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
    vhosts = {"127.0.0.1":"localhost","129.161.209.91":"I.Created.You"}
    types = {
        "user": IRCUser,
        "server": IRCServer,
        "service": IRCService,
    }
    prefix_order = "qaohv" # Hardcoded into modes :(
    prefix_symbols = {
        "q": "~",
        "a": "&",
        "o": "@",
        "h": "%",
        "v": "+"
    }

    def __init__(self, name, client_timeout=5 * 60, description="Welcome to TXIRCd"):
        self.name = name
        self.hostname = socket.getfqdn()
        self.version = "0.1"
        self.created = now()
        self.token = uuid.uuid1()
        self.motd = description
        self.motd_length = 80
        self.client_timeout = client_timeout
        self.servers = CaseInsensitiveDictionary()
        self.users = CaseInsensitiveDictionary()
        self.channels = DefaultCaseInsensitiveDictionary(self.ChannelFactory)

    def ChannelFactory(self, name):
        c = Channel(name,now(),{"message":None,"author":"","created":now()},CaseInsensitiveDictionary(),ChannelModes(self,None))
        c.mode.parent = c
        c.mode.combine("nt",[],name)
        return c
