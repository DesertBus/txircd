from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower

class NickServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], " ".join(data["params"])])

class ChanServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], " ".join(data["params"])])

class BidServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], " ".join(data["params"])])

class OperServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_operserv_nick"], " ".join(data["params"])])

class NSIdentifyCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "IDENTIFY {}".format(" ".join(data["params"]))])

class NSGhostCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "GHOST {}".format(" ".join(data["params"]))])

class NSLoginCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "LOGIN {}".format(" ".join(data["params"]))])

class NSLogoutCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "LOGOUT {}".format(" ".join(data["params"]))])

class NSDropCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "DROP {}".format(" ".join(data["params"]))])

class NSNicklistCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "NICKLIST {}".format(" ".join(data["params"]))])

class NSAccountCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "ACCOUNT {}".format(" ".join(data["params"]))])

class NSCertCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], "CERT {}".format(" ".join(data["params"]))])

class CSRegisterCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], "REGISTER {}".format(" ".join(data["params"]))])

class CSAccessCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], "ACCESS {}".format(" ".join(data["params"]))])

class CSCdropCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], "CDROP {}".format(" ".join(data["params"]))])

class BSStartCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "START {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "START", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSStopCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "STOP {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "STOP", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSBidCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "BID {}".format(" ".join(data["params"]))])

class BSRevertCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "REVERT {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "REVERT", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSOnceCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "ONCE {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "ONCE", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSTwiceCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "TWICE {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "TWICE", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSSoldCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "SOLD {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SOLD", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "bidserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSHighbidderCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "HIGHBIDDER {}".format(" ".join(data["params"]))])

class BSCurrentAuctionCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "CURRENTAUCTION {}".format(" ".join(data["params"]))])

class OSServAdminCommand(Command):
    def __init__(self, module):
        self.module = module
    
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_operserv_nick"], "SERVADMIN {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SERVADMIN", ":You have not registered")
            return {}
        if not self.module.isServiceAdmin(user, "operserv"):
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.serviceServer = None
        self.blockedUsers = set()
        self.admins = {}
    
    def spawn(self):
        if "services_nickserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_nick"] = "NickServ"
        if "services_chanserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_nick"] = "ChanServ"
        if "services_bidserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_nick"] = "BidServ"
        if "services_operserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_operserv_nick"] = "OperServ"
        return {
            "commands": {
                "NICKSERV": NickServAlias(),
                "NS": NickServAlias(),
                "CHANSERV": ChanServAlias(),
                "CS": ChanServAlias(),
                "BIDSERV": BidServAlias(),
                "BS": BidServAlias(),
                "OPERSERV": OperServAlias(),
                "OS": OperServAlias(),
                
                "IDENTIFY": NSIdentifyCommand(),
                "ID": NSIdentifyCommand(),
                "GHOST": NSGhostCommand(),
                "LOGIN": NSLoginCommand(),
                "LOGOUT": NSLogoutCommand(),
                "DROP": NSDropCommand(),
                "NICKLIST": NSNicklistCommand(),
                "ACCOUNT": NSAccountCommand(),
                "CERT": NSCertCommand(),
                
                "REGISTER": CSRegisterCommand(),
                "ACCESS": CSAccessCommand(),
                "CDROP": CSCdropCommand(),
                
                "START": BSStartCommand(self),
                "STOP": BSStopCommand(self),
                "BID": BSBidCommand(),
                "REVERT": BSRevertCommand(self),
                "ONCE": BSOnceCommand(self),
                "TWICE": BSTwiceCommand(self),
                "SOLD": BSSoldCommand(self),
                "HIGHBIDDER": BSHighbidderCommand(),
                "CURRENTAUCTION": BSCurrentAuctionCommand(),
                
                "SERVADMIN": OSServAdminCommand(self)
            },
            "actions": {
                "commandpermission": self.commandPermission,
                "netsplit": self.onNetsplit
            },
            "server": {
                "ServiceServer": self.noteServer,
                "ServiceBlockUser": self.addBlock,
                "ServiceUnblockUser": self.removeBlock,
                "ServiceAdmins": self.setAdmins,
                "ServiceLogin": self.loginUser,
                "ServiceLogout": self.logoutUser
            }
        }
    
    def commandPermission(self, user, cmd, data):
        if cmd == "NICK" and data["nick"] in [ self.ircd.servconfig["services_nickserv_nick"], self.ircd.servconfig["services_chanserv_nick"], self.ircd.servconfig["services_bidserv_nick"] ]:
            user.sendMessage(irc.ERR_ERRONEUSNICKNAME, data["nick"], ":Invalid nickname: Reserved for Services")
            return {}
        if self.ircd.servconfig["services_nickserv_nick"] not in self.ircd.users:
            return data
        nickserv = self.ircd.users[self.ircd.servconfig["services_nickserv_nick"]]
        if user not in self.blockedUsers:
            return data
        if cmd == "PRIVMSG":
            to_nickserv = False
            for u in data["targetuser"]:
                if irc_lower(u.nickname) == irc_lower(nickserv.nickname):
                    to_nickserv = True
                    break
            if to_nickserv:
                data["targetuser"] = [nickserv]
                data["targetchan"] = []
                data["chanmod"] = []
                return data
            user.sendMessage("NOTICE", ":You cannot message anyone other than NickServ until you identify or change nicks.", prefix=nickserv.prefix())
            return {}
        if cmd in [ "PING", "PONG", "NICK", "QUIT", "NS", "NICKSERV", "LOGIN", "ID", "IDENTIFY" ]:
            return data
        user.sendMessage("NOTICE", ":You cannot use the command \x02{}\x02 until you identify or change nicks.".format(cmd), prefix=nickserv.prefix())
        return {}
    
    def onNetsplit(self, name):
        if name == self.serviceServer:
            self.blockedUsers = set()
            self.serviceServer = None
            self.admins = {}
            for u in self.ircd.users:
                if "accountid" in u.cache:
                    del u.cache["accountid"]
    
    def noteServer(self, command, args):
        self.serviceServer = args[0]
    
    def addBlock(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        self.blockedUsers.add(self.ircd.userid[args[0]])
    
    def removeBlock(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        self.blockedUsers.discard(self.ircd.userid[args[0]])
    
    def setAdmins(self, command, args):
        service = args.pop(0)
        self.admins[service] = args
    
    def loginUser(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        self.ircd.userid[args[0]].cache["accountid"] = args[1]
    
    def logoutUser(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        del self.ircd.userid[args[0]].cache["accountid"]
    
    def isServiceAdmin(self, user, service):
        if service not in self.admins:
            return False
        if "accountid" not in user.cache:
            return False
        return user.cache["accountid"] in self.admins[service]