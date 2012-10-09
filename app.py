# -*- coding: utf-8 -*-
from twisted.internet import reactor, ssl
from twisted.python import log
from txircd.ircd import IRCD, default_options
import yaml, collections

if __name__ == "__main__":
    # Copy the defaults
    options = default_options.copy()
    # Parse command line
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="txircd.yaml")
    parser.add_argument("--irc-port", dest="ircport", type=int)
    parser.add_argument("--ssl-port", dest="sslport", type=int)
    parser.add_argument("--name")
    parser.add_argument("--motd")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true")
    parser.add_argument("--client-timeout", dest="client_timeout", type=int)
    args = parser.parse_args()
    # Load config file
    try:
        with open(args.config) as f:
            options.update(yaml.safe_load(f))
    except:
        pass # Oh well
    # Update options with command line values
    if args.verbose:
        options["verbose"] = True
    if args.ircport:
        options["irc_port"] = args.ircport
    if args.sslport:
        options["ssl_port"] = args.sslport
    if args.name:
        options["name"] = args.name
    if args.motd:
        options["motd"] = args.motd
    if args.client_timeout:
        options["client_timeout"] = args.client_timeout
    # Save the set values to the config file (if we can)
    try:
        with open(args.config,"w") as f:
            yaml.dump(options, f, default_flow_style=False)
    except:
        pass # Oh well
    # Finally launch the app with the options
    if options["verbose"]:
        import sys
        log.startLogging(sys.stdout)
    ircd = IRCD(args.config, options)
    ssl_cert = ssl.DefaultOpenSSLContextFactory("test.key","test.pem")
    if options["irc_port"]:
        if isinstance(options["irc_port"], collections.Sequence):
            for port in options["irc_port"]:
                try:
                    reactor.listenTCP(int(port), ircd)
                except:
                    pass # Wasn't a number
        else:
            try:
                reactor.listenTCP(int(options["irc_port"]), ircd)
            except:
                pass # Wasn't a number
    if options["ssl_port"]:
        if isinstance(options["ssl_port"], collections.Sequence):
            for port in options["ssl_port"]:
                try:
                    reactor.listenSSL(int(port), ircd, ssl_cert)
                except:
                    pass # Wasn't a number
        else:
            try:
                reactor.listenSSL(int(options["ssl_port"]), ircd, ssl_cert)
            except:
                pass # Wasn't a number
    # And start up the reactor
    reactor.run()

