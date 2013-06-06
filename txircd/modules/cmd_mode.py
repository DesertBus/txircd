from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower, epoch

class ModeCommand(Command):
    def onUse(self, user, data):
        if "targetchan" in data:
            if "modes" in data:
                data["targetchan"].setMode(user, data["modes"], data["params"])
            else:
                channel = data["targetchan"]
                user.sendMessage(irc.RPL_CHANNELMODEIS, channel.name, channel.modeString(user))
                user.sendMessage(irc.RPL_CREATIONTIME, channel.name, str(epoch(channel.created)))
        elif "targetuser" in data:
            if user == data["targetuser"]:
                if "modes" in data:
                    data["targetuser"].setMode(user, data["modes"], data["params"])
                else:
                    user.sendMessage(irc.RPL_UMODEIS, user.modeString(user))
            else:
                user.sendMessage(irc.ERR_USERSDONTMATCH, ":Can't operate on modes for other users")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "MODE", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters")
            return {}
        if params[0] in self.ircd.users:
            if len(params) > 1 and params[1]:
                return {
                    "user": user,
                    "targetuser": self.ircd.users[params[0]],
                    "modes": params[1],
                    "params": params[2:]
                }
            return {
                "user": user,
                "targetuser": self.ircd.users[params[0]]
            }
        if params[0] in self.ircd.channels:
            cdata = self.ircd.channels[params[0]]
            if not user.hasAccess(cdata.name, self.ircd.servconfig["channel_minimum_level"]["MODE"]):
                if len(params) > 2:
                    user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You must have channel operator access to set channel modes")
                    return {}
                if len(params) > 1:
                    for mode in params[1]:
                        if mode == "+" or mode == "-":
                            continue
                        if mode in self.ircd.channel_mode_type and self.ircd.channel_mode_type[mode] != 0:
                            user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You must have channel operator access to set channel modes")
                            return {}
            if len(params) > 1 and params[1]:
                return {
                    "user": user,
                    "targetchan": cdata,
                    "modes": params[1],
                    "params": params[2:]
                }
            return {
                "user": user,
                "targetchan": cdata
            }
        user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
        return {}

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        if "channel_minimum_level" not in self.ircd.servconfig:
            self.ircd.servconfig["channel_minimum_level"] = {}
        if "MODE" not in self.ircd.servconfig["channel_minimum_level"]:
            self.ircd.servconfig["channel_minimum_level"]["MODE"] = "o"
        return {
            "commands": {
                "MODE": ModeCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["MODE"]