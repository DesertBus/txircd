from twisted.words.protocols import irc
from txircd.modbase import Command

class AwayCommand(Command):
    def onUse(self, user, data):
        if "reason" in data:
            user.setMetadata("ext", "away", data["reason"])
            user.sendMessage(irc.RPL_NOWAWAY, ":You have been marked as being away")
        else:
            if "away" in user.metadata["ext"]:
                user.delMetadata("ext", "away")
            user.sendMessage(irc.RPL_UNAWAY, ":You are no longer marked as being away")
    
    def processParams(self, user, params):
        if not params or not params[0]:
            return {
                "user": user
            }
        return {
            "user": user,
            "reason": params[0]
        }
    
    def reply(self, command, data):
        if command not in ["PRIVMSG", "INVITE"]:
            return
        if "targetuser" not in data:
            return
        sourceUser = data["user"]
        if command == "PRIVMSG":
            for user in data["targetuser"]:
                if "away" in user.metadata["ext"]:
                    sourceUser.sendMessage(irc.RPL_AWAY, user.nickname, ":{}".format(user.metadata["ext"]["away"]))
        elif command == "INVITE":
            if "away" in targetUser.metadata["ext"]:
                data["user"].sendMessage(irc.RPL_AWAY, targetUser.nickname, ":{}".format(targetUser.metadata["ext"]["away"]))
    
    def whoisLine(self, user, target):
        if "away" in target.metadata["ext"]:
            user.sendMessage(irc.RPL_AWAY, target.username, ":{}".format(target.metadata["ext"]["away"]))

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.awayCmd = None
    
    def spawn(self):
        self.awayCmd = AwayCommand()
        return {
            "commands": {
                "AWAY": self.awayCmd
            },
            "actions": {
                "commandextra": self.awayCmd.reply,
                "whoisdata": self.awayCmd.whoisLine
            }
        }
    
    def cleanup(self):
        self.ircd.actions["commandextra"].remove(self.awayCmd.reply)
        self.ircd.actions["whoisdata"].remove(self.awayCmd.whoisLine)
        del self.ircd.commands["AWAY"]