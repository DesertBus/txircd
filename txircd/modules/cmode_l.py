from twisted.words.protocols import irc
from txircd.modbase import Mode

class LimitMode(Mode):
    def checkSet(self, user, target, param):
        intParam = int(param)
        if str(intParam) != param:
            return [False, param]
        return [(intParam >= 0), param]
    
    def checkPermission(self, user, cmd, data):
        if cmd != "JOIN":
            return data
        targetChannels = data["targetchan"]
        keys = data["keys"]
        removeChannels = []
        for channel in targetChannels:
            if "l" in channel.mode and len(channel.users) >= int(channel.mode["l"]):
                user.sendMessage(irc.ERR_CHANNELISFULL, channel.name, ":Cannot join channel (Channel is full)")
                removeChannels.append(channel)
        
        for channel in removeChannels:
            index = targetChannels.index(channel)
            targetChannels.pop(index)
            keys.pop(index)
        data["targetchan"] = targetChannels
        data["keys"] = keys
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "cpl": LimitMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("cpl")