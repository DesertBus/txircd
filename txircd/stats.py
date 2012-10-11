# -*- coding: utf-8 -*-

from twisted.internet.protocol import Factory, Protocol

class StatProtocol(Protocol):
    def connectionMade(self):
        self.factory.addProtocol(self)
    
    def connectionLost(self, reason=None):
        self.factory.delProtocol(self)

class StatFactory(Factory):
    protocol = StatProtocol
    
    def __init__(self):
        self.conns = []
    
    def addProtocol(self, p):
        self.conns.append(p)
    
    def delProtocol(self, p):
        self.conns.remove(p)
    
    def broadcast(self, message):
        for p in self.conns:
            p.transport.write(message)