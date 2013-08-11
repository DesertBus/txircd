from txircd.modbase import Module

class AwayNotify(Module):
    def capRequest(self, user, capability):
        return True
    
    def capAcknowledge(self, user, capability):
        return False
    
    def capRequestRemove(self, user, capability):
        return True
    
    def capAcknowledgeRemove(self, user, capability):
        return False
    
    def capClear(self, user, capability):
        return True
    
    def notifyUsers(self, user, namespace, key, oldValue, value):
        try:
            if not (namespace == "ext" and key == "away"):
                return
            message = value
            if "away" not in user.metadata["ext"]:
                message = None
            notify = set()
            for channel in self.ircd.channels.itervalues():
                if user in channel.users:
                    for u in channel.users.iterkeys():
                        notify.add(u)
            notify.remove(user)
            for u in notify:
                if "cap" in u.cache and "away-notify" in u.cache["cap"]:
                    if message is None:
                        u.sendMessage("AWAY", to=None, prefix=user.prefix())
                    else:
                        u.sendMessage("AWAY", ":{}".format(message), to=None, prefix=user.prefix())
        except:
            pass
    
    def notifyOnJoin(self, user, channel):
        if "away" in user.metadata["ext"]:
            for u in channel.users.iterkeys():
                if u != user and u.server == self.ircd.name and "cap" in u.cache and "away-notify" in u.cache["cap"]:
                    u.sendMessage("AWAY", ":{}".format(user.metadata["ext"]["away"]), to=None, prefix=user.prefix())

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.away_notify = None
    
    def spawn(self):
        self.away_notify = AwayNotify().hook(self.ircd)
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["away-notify"] = self.away_notify
        return {
            "actions": {
                "join": [self.away_notify.notifyOnJoin],
                "metadataupdate": [self.away_notify.notifyUsers]
            }
        }
    
    def cleanup(self):
        del self.ircd.module_data_cache["cap"]["away-notify"]
        self.ircd.actions["join"].remove(self.away_notify.notifyOnJoin)
        self.ircd.actions["metadataupdate"].remove(self.away_notify.notifyUsers)