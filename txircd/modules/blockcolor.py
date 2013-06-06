from txircd.modbase import Mode

class BlockColor(Mode):
    def checkPermission(self, user, cmd, data):
        if cmd not in ["PRIVMSG", "NOTICE"]:
            return data
        if chr(2) not in data["message"] and chr(3) not in data["message"] and chr(15) not in data["message"] and chr(22) not in data["message"] and chr(29) not in data["message"] and chr(31) not in data["message"]:
            return data
        okchans = []
        okchanmods = []
        exempt_chanops = "c" in self.ircd.servconfig["channel_exempt_chanops"] 
        for index, chan in enumerate(data["targetchan"]):
            if "c" not in chan.mode or (exempt_chanops and user.hasAccess(chan.name, "o")):
                okchans.append(chan)
                okchanmods.append(data["chanmod"][index])
        data["targetchan"] = okchans
        data["chanmod"] = okchanmods
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "cnc": BlockColor()
            }
        }
    
    def cleanup(self):
        self.ircd.removeMode("cnc")