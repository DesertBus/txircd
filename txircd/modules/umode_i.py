from txircd.modbase import Mode

class InvisibleMode(Mode):
    def namesListEntry(self, recipient, channel, user, representation):
        if channel.name not in recipient.channels and "i" in user.mode:
            return ""
        return representation
    
    def checkWhoVisible(self, user, targetUser, filters, fields, channel, udata):
        if channel:
            if channel.name not in user.channels and "i" in targetUser.mode:
                return {}
        if "i" in targetUser.mode:
            share_channel = False
            for chan in user.channels:
                if chan in targetUser.channels:
                    share_channel = True
                    break
            if not share_channel:
                return {}
        return udata

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
                "wholinemodify": [self.invisible_mode.checkWhoVisible]
            }
        }
    
    def cleanup(self):
        self.ircd.removeMode("uni")
        self.ircd.actions["wholinemodify"].remove(self.invisible_mode.checkWhoVisible)