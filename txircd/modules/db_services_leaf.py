from twisted.words.protocols import irc
from txircd.modbase import Command

class NickServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], " ".join(data["params"])])

class ChanServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], " ".join(data["params"])])

class BidServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], " ".join(data["params"])])

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
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "START {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSStopCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "STOP {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
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
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "REVERT {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSOnceCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "ONCE {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSTwiceCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "TWICE {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        return {
            "user": user,
            "params": params
        }

class BSSoldCommand(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], "SOLD {}".format(" ".join(data["params"]))])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
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

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.blockedUsers = set()
    
    def spawn(self):
        if "services_nickserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_nick"] = "NickServ"
        if "services_chanserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_nick"] = "ChanServ"
        if "services_bidserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_nick"] = "BidServ"
        return {
            "commands": {
                "NICKSERV": NickServAlias(),
                "NS": NickServAlias(),
                "CHANSERV": ChanServAlias(),
                "CS": ChanServAlias(),
                "BIDSERV": BidServAlias(),
                "BS": BidServAlias(),
                
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
                
                "START": BSStartCommand(),
                "STOP": BSStopCommand(),
                "BID": BSBidCommand(),
                "REVERT": BSRevertCommand(),
                "ONCE": BSOnceCommand(),
                "TWICE": BSTwiceCommand(),
                "SOLD": BSSoldCommand(),
                "HIGHBIDDER": BSHighbidderCommand(),
                "CURRENTAUCTION": BSCurrentAuctionCommand()
            },
            "actions": {
                "commandpermission": [self.commandPermission]
            },
            "server": {
                "ServiceBlockUser": self.addBlock,
                "ServiceUnblockUser": self.removeBlock
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["NICKSERV"]
        del self.ircd.commands["NS"]
        del self.ircd.commands["CHANSERV"]
        del self.ircd.commands["CS"]
        del self.ircd.commands["BIDSERV"]
        del self.ircd.commands["BS"]
        
        del self.ircd.commands["IDENTIFY"]
        del self.ircd.commands["ID"]
        del self.ircd.commands["GHOST"]
        del self.ircd.commands["LOGIN"]
        del self.ircd.commands["LOGOUT"]
        del self.ircd.commands["DROP"]
        del self.ircd.commands["NICKLIST"]
        del self.ircd.commands["ACCOUNT"]
        del self.ircd.commands["CERT"]
        
        del self.ircd.commands["REGISTER"]
        del self.ircd.commands["ACCESS"]
        del self.ircd.commands["CDROP"]
        
        del self.ircd.commands["START"]
        del self.ircd.commands["STOP"]
        del self.ircd.commands["BID"]
        del self.ircd.commands["REVERT"]
        del self.ircd.commands["ONCE"]
        del self.ircd.commands["TWICE"]
        del self.ircd.commands["SOLD"]
        del self.ircd.commands["HIGHBIDDER"]
        del self.ircd.commands["CURRENTAUCTION"]
        
        self.ircd.actions["commandpermission"].remove(self.commandPermission)
        
        self.ircd.server_commands["ServiceBlockUser"].remove(self.addBlock)
        self.ircd.server_commands["ServiceUnblockUser"].remove(self.removeBlock)
    
    def commandPermission(self, user, cmd, data):
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
    
    def addBlock(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        self.blockedUsers.add(self.ircd.userid[args[0]])
    
    def removeBlock(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        self.blockedUsers.discard(self.ircd.userid[args[0]])