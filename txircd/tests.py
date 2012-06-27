# -*- coding: utf-8 -*-
from twisted.internet import reactor, protocol
from twisted.trial import unittest
from .ircd import IRCD
from twisted.words.protocols.irc import IRCClient


class NoLoginClient(IRCClient):
    performLogin = 0


class IRCDTests(unittest.TestCase):
    def setUp(self):
        self.ircd = IRCD()
        self.port = reactor.listenTCP(0, self.ircd, interface="127.0.0.1")
        self.client = None

    def tearDown(self):
        if self.client is not None:
            self.client.transport.loseConnection()
        return self.port.stopListening()

    def build_client(self, client_class=IRCClient):
        creator = protocol.ClientCreator(reactor, client_class)

        def cb(client):
            self.client = client
            return client

        return creator.connectTCP('127.0.0.1', self.port.getHost().port).addCallback(cb)
