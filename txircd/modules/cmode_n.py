from twisted.words.protocols import irc
from txircd.modbase import Mode

class NoExternalMessagesMode(Mode):
    def checkPermission(self, user, cmd, data):
        if cmd not in ["PRIVMSG", "NOTICE"]:
            return data
        
        targetChannels = data["targetchan"]
        chanModList = data["chanmod"]
        removeTargets = []
        
        for channel in targetChannels:
            if "n" in channel.mode and user not in channel.users:
                removeTargets.append(channel)
                user.sendMessage(irc.ERR_CANNOTSENDTOCHAN, channel.name, ":Cannot send to channel (no external messages)")
        
        for channel in removeTargets:
            index = targetChannels.index(channel)
            targetChannels.pop(index)
            chanModList.pop(index)
        
        data["targetchan"] = targetChannels
        data["chanmod"] = chanModList
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "cnn": NoExternalMessagesMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("cnn")