# -*- coding: utf-8 -*-


class IRCService(object):
    def __init__(self, parent, service, password):
        pass

    def irc_unknown(self, prefix, command, params):
        raise NotImplementedError(command, prefix, params)
