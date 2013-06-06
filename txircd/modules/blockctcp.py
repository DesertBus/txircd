from txircd.modbase import Mode

class BlockCTCP(Mode):
    def has_CTCP(self, msg):
        if chr(1) not in msg:
            return False
        findpos = msg.find(chr(1))
        in_action = False
        while findpos > -1:
            if in_action or (msg[findpos+1:findpos+7] == "ACTION" and len(msg) > findpos + 7 and msg[findpos+7] == " "):
                in_action = not in_action
                findpos = msg.find(chr(1), findpos + 1)
            else:
                return True
        return False
    
    def checkPermission(self, user, cmd, data):
        if cmd not in ["PRIVMSG", "NOTICE"]:
            return data
        if self.has_CTCP(data["message"]):
            exempt_chanops = "C" in self.ircd.servconfig["channel_exempt_chanops"]
            okchans = []
            okchanmod = []
            for index, chan in enumerate(data["targetchan"]):
                if "C" not in chan.mode or (exempt_chanops and user.hasAccess(chan.name, "o")):
                    okchans.append(chan)
                    okchanmod.append(data["chanmod"][index])
            data["targetchan"] = okchans
            data["chanmod"] = okchanmod
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "cnC": BlockCTCP()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("cnC")