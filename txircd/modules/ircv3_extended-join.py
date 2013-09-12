from txircd.modbase import Module

class ExtendedJoin(Module):
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
    
    def modifyJoinMessage(self, channel, user, joinShowUser):
        if "extended_join_wait" in channel.cache:
            del channel.cache["extended_join_wait"]
            remove = []
            for u in joinShowUser:
                if "cap" in u.cache and "extended-join" in u.cache["cap"]:
                    remove.append(u)
                    u.sendMessage("JOIN", user.metadata["ext"]["accountname"] if "accountname" in user.metadata["ext"] else "*", ":{}".format(user.realname), to=channel.name, prefix=user.prefix())
            for u in remove:
                joinShowUser.remove(u)
            return joinShowUser
        else:
            channel.cache["extended_join_wait"] = True
            return "again" # force this module to have lower priority so it goes last, after any modules that may actually hide the join notice

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.extended_join = None
    
    def spawn(self):
        self.extended_join = ExtendedJoin().hook(self.ircd)
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["extended-join"] = self.extended_join
        return {
            "actions": {
                "joinmessage": self.extended_join.modifyJoinMessage
            }
        }
    
    def cleanup(self):
        del self.ircd.module_data_cache["cap"]["extended-join"]