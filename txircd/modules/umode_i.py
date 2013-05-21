from txircd.modbase import Mode

class InvisibleMode(Mode):
    def namesListEntry(self, recipient, channel, user, representation):
        if channel.name not in recipient.channels and "i" in user.mode:
            return ""
        return representation
    
    def checkWhoVisible(self, cmd, data):
        if cmd != "WHO":
            return
        if "data" not in data or not data["data"] or data["phase"] != "detect":
            # the request didn't match anyone or some other module already ate the data or it's not the right phase
            return
        destination = data["data"]["dest"]
        if destination[0] == "#":
            if destination not in data["user"].channels and "i" in data["targetuser"].mode:
                data["data"] = {}
        elif "i" in data["targetuser"].mode:
            target = data["targetuser"]
            share_channel = False
            for chan in data["user"].channels:
                if chan in target.channels:
                    share_channel = True
                    break
            if not share_channel:
                data["data"] = {}

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.invisible_mode = None
    
    def spawn(self):
        self.invisible_mode = InvisibleMode()
        return {
            "modes": {
                "uni": self.invisible_mode
            },
            "actions": {
                "commandextra": [self.invisible_mode.checkWhoVisible]
            }
        }
    
    def cleanup(self):
        self.ircd.removeMode("uni")
        self.ircd.actions["commandextra"].remove(self.invisible_mode.checkWhoVisible)