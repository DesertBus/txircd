from twisted.words.protocols import irc
from txircd.modbase import Command

# These numerics are defined for use in the IRCv3 SASL documentation
# located at http://ircv3.atheme.org/extensions/sasl-3.1
# The names are entirely made up based on their uses.
irc.RPL_SASLACCOUNT = "900"
irc.RPL_SASLSUCCESS = "903"
irc.ERR_SASLFAILED = "904"
irc.ERR_SASLABORTED = "906"
irc.ERR_SASLALREADYAUTHED = "907"

class Sasl(Command):
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
        if "sasl_authenticating" not in user.cache:
            mechanism = data["authentication"][0].upper()
            user.cache["sasl_authenticating"] = data["authentication"][0].upper()
            if "server_sasl_agent" in self.ircd.servconfig and self.ircd.servconfig["server_sasl_agent"]:
                pass # TODO after s2s
            elif "sasl_agent" in self.ircd.module_data_cache:
                result = self.ircd.module_data_cache["sasl_agent"].saslStart(user, mechanism)
                if result == "fail":
                    self.sendFailure(user)
            else:
                del user.cache["sasl_authenticating"]
                user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
        else:
            if "server_sasl_agent" in self.ircd.servconfig and self.ircd.servconfig["server_sasl_agent"]:
                pass # TODO after s2s
            else:
                result = self.ircd.module_data_cache["sasl_agent"].saslNext(user, data["authentication"])
                if result == "done":
                    if "accountname" in user.metadata["ext"]:
                        self.sendSuccess(user)
                        self.ircd.module_data_cache["sasl_agent"].saslDone(user, True)
                    else:
                        self.sendFailure(user)
                        self.ircd.module_data_cache["sasl_agent"].saslDone(user, False)
                elif result == "wait":
                    self.ircd.module_data_cache["sasl_agent"].bindSaslResult(user, self.sendSuccess, self.sendFailure)
    
    def processParams(self, user, params):
        if user.registered == 0:
            user.sendMessage(irc.ERR_ALREADYREGISTRED, ":You may not reregister")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "AUTHENTICATE", ":Not enough parameters")
            return {}
        if "accountname" in user.metadata["ext"]:
            user.sendMessage(irc.ERR_SASLALREADYAUTHED, ":You have already authenticated")
            return {}
        return {
            "user": user,
            "authentication": params[0]
        }
    
    def checkInProgress(self, user):
        if "sasl_authenticating" in user.cache:
            del user.cache["sasl_authenticating"]
            user.sendMessage(irc.ERR_SASLABORTED, ":SASL authentication aborted")
        return True
    
    def sendSuccess(self, user):
        user.sendMessage(irc.RPL_SASLACCOUNT, "{}!{}@{}".format(user.nickname if user.nickname else "unknown", user.username if user.username else "unknown", user.hostname), user.metadata["ext"]["accountname"], ":You are now logged in as {}".format(user.metadata["ext"]["accountname"]))
        user.sendMessage(irc.RPL_SASLSUCCESS, ":SASL authentication successful")
        del user.cache["sasl_authenticating"]
    
    def sendFailure(self, user):
        user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
        del user.cache["sasl_authenticating"]

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.sasl = None
    
    def spawn(self):
        self.sasl = Sasl()
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["sasl"] = self.sasl
        if "sasl_mechanisms" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["sasl_mechanisms"] = {}
        if "server_sasl_agent" not in self.ircd.servconfig:
            self.ircd.servconfig["sasl_agent"] = "" # default to an internal agent, at least until we get s2s going
        return {
            "commands": {
                "AUTHENTICATE": self.sasl
            },
            "actions": {
                "register": [self.sasl.checkInProgress]
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["AUTHENTICATE"]
        del self.ircd.module_data_cache["cap"]["sasl"]
        self.ircd.actions["register"].remove(self.sasl.checkInProgress)