# -*- coding: utf-8 -*-
from twisted.internet import reactor
from twisted.python import log
from txircd.ircd import IRCD


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--irc-port', dest='ircport', default=6667, type=int)
    parser.add_argument('--name', default='txircd')
    parser.add_argument('--welcome', default='Welcome to TXIRCd')
    parser.add_argument('-v', '--verbose', dest='verbose', default=False, action='store_true')
    parser.add_argument('--client-timeout', dest='client_timeout', default=60 * 3, type=int)
    args = parser.parse_args()
    if args.verbose:
        import sys
        log.startLogging(sys.stdout)
    ircd = IRCD(args.name, client_timeout=args.client_timeout, welcome_message=args.welcome)
    reactor.listenTCP(args.ircport, ircd)
    reactor.run()

