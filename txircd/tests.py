# -*- coding: utf-8 -*-
from twisted.internet import reactor, protocol
from twisted.trial import unittest
from twisted.words.protocols import irc
from .ircd import IRCD


class NoLoginClient(irc.IRCCLient):
    performLogin = 0


class IRCDTests(unittest.TestCase):
    def setUp(self):
        factory = IRCD()
        self.port = reactor.listenTCP(0, factory, interface="127.0.0.1")
        self.client = None

    def tearDown(self):
        if self.client is not None:
            self.client.transport.loseConnection()
        return self.port.stopListening()

    def build_client(self, client_class=irc.IRCClient):
        creator = protocol.ClientCreator(reactor, client_class)

        def cb(client):
            self.client = client

        return creator.connectTCP('127.0.0.1', self.port.getHost().port).addCallback(cb)

    def test_register(self):
        deferred = self.build_client(NoLoginClient)
        deferred.addCallback()
