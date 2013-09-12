from txircd.modbase import Module

class AccountNotify(Module):
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
            user.nickname # Cause a failure if it's not a user
            if not (namespace == "ext" and key == "accountname"):
                return
            notify = set()
            for channel in self.ircd.channels.itervalues():
                if user in channel.users:
                    for u in channel.users.iterkeys():
                        notify.add(u)
            notify.remove(user)
            for u in notify:
                if "cap" in u.cache and "account-notify" in u.cache["cap"]:
                    u.sendMessage("ACCOUNT", value if value else "*", to=None, prefix=user.prefix())
        except:
            pass # This will fail very quickly if it's a channel.  Just do nothing in that case.

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.account_notify = None
    
    def spawn(self):
        self.account_notify = AccountNotify().hook(self.ircd)
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["account-notify"] = self.account_notify
        return {
            "actions": {
                "metadataupdate": self.account_notify.notifyUsers
            }
        }
    
    def cleanup(self):
        del self.ircd.module_data_cache["cap"]["account-notify"]
        self.ircd.actions["metadataupdate"].remove(self.account_notify.notifyUsers)