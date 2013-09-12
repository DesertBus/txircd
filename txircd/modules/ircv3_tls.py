from twisted.internet.interfaces import ITLSTransport, ISSLTransport
from twisted.words.protocols import irc
from txircd.modbase import Command

# Numerics and names are taken from the IRCv3.1 STARTTLS spec
# http://ircv3.atheme.org/extensions/tls-3.1
irc.RPL_STARTTLS = "670"
irc.ERR_STARTTLS = "691"

class StartTLSCommand(Command):
    def capRequest(self, user, capability):
        return True
    
    def capAcknowledge(self, user, capability):
        return False
    
    def capRequestRemove(self, user, capability):
        return True
    
    def capAcknowledgeRemove(self, user, capability):
        return False
    
    def capClear(self, user, capability):
        return True
    
    def onUse(self, user, data):
        try:
            user.socket.transport = ITLSTransport(user.socket.transport)
        except:
            user.sendMessage(irc.ERR_STARTTLS, ":STARTTLS failed")
        else:
            user.sendMessage(irc.RPL_STARTTLS, ":STARTTLS successful, proceed with TLS handshake")
            user.socket.transport.startTLS(self.ircd.ssl_cert)
            user.socket.secure = ISSLTransport(user.socket.transport, None) is not None
    
    def processParams(self, user, params):
        if user.registered == 0:
            user.sendMessage(irc.ERR_STARTTLS, ":You can't STARTTLS after registration")
            return {}
        return {
            "user": user
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        tls = StartTLSCommand()
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["tls"] = tls
        return {
            "commands": {
                "STARTTLS": tls
            }
        }
    
    def cleanup(self):
        del self.ircd.module_data_cache["cap"]["tls"]