from twisted.internet import reactor, ssl
from twisted.internet.endpoints import serverFromString
from twisted.python import log
from txircd.ircd import IRCD, default_options
from txircd.server import ServerFactory
from txircd.utils import resolveEndpointDescription
from OpenSSL import SSL
import yaml, collections, sys, signal

# A direct copy of DefaultOpenSSLContext factory as of Twisted 12.2.0
# The only difference is using ctx.use_certificate_chain_file instead of ctx.use_certificate_file
# This code remains unchanged in the newer Twisted 13.0.0
class ChainedOpenSSLContextFactory(ssl.DefaultOpenSSLContextFactory):
    def cacheContext(self):
        if self._context is None:
            ctx = self._contextFactory(self.sslmethod)
            ctx.set_options(SSL.OP_NO_SSLv2)
            ctx.use_certificate_chain_file(self.certificateFileName)
            ctx.use_privatekey_file(self.privateKeyFileName)
            self._context = ctx

def createHangupHandler(ircd):
    return lambda signal, stack: ircd.rehash()

def addClientPortToIRCd(port, ircd, desc):
    ircd.saveClientPort(desc, port)

def addServerPortToIRCd(port, ircd, desc):
    ircd.saveServerPort(desc, port)

def logPortNotBound(error):
    log.msg("An error occurred: {}".format(error))

if __name__ == "__main__":
    # Copy the defaults
    options = default_options.copy()
    # Parse command line
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="txircd.yaml")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true")
    parser.add_argument("-l", "--log-file", dest="log_file", type=argparse.FileType('a'), default=sys.stdout)
    args = parser.parse_args()
    # Load config file
    try:
        with open(args.config) as f:
            options.update(yaml.safe_load(f))
    except:
        pass # Oh well
    if options["app_verbose"] or args.verbose:
        log.startLogging(args.log_file)
    ssl_cert = ChainedOpenSSLContextFactory(options["app_ssl_key"],options["app_ssl_pem"])
    ssl_cert.getContext().set_verify(SSL.VERIFY_PEER, lambda connection, x509, errnum, errdepth, ok: True) # We can ignore the validity of certs to get what we need
    ircd = IRCD(args.config, options, ssl_cert)
    serverlink_factory = ServerFactory(ircd)
    for portstring in options["server_client_ports"]:
        try:
            endpoint = serverFromString(reactor, resolveEndpointDescription(portstring))
        except ValueError:
            log.msg("Could not bind {}: not a valid description".format(portstring))
            continue
        listenDeferred = endpoint.listen(ircd)
        listenDeferred.addCallback(addClientPortToIRCd, ircd, portstring)
        listenDeferred.addErrback(logPortNotBound)
    for portstring in options["server_link_ports"]:
        try:
            endpoint = serverFromString(reactor, resolveEndpointDescription(portstring))
        except ValueError:
            log.msg("Could not bind {}: not a valid description".format(portstring))
            continue
        listenDeferred = endpoint.listen(serverlink_factory)
        listenDeferred.addCallback(addServerPortToIRCd, ircd, portstring)
        listenDeferred.addErrback(logPortNotBound)
    # Bind SIGHUP to rehash
    signal.signal(signal.SIGHUP, createHangupHandler(ircd))
    # And start up the reactor
    reactor.run()