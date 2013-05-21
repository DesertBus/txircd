from txircd.modbase import Module

class MultiPrefix(Module):
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
    
    def namesListEntry(self, user, channel, listingUser, representation):
        if "cap" not in user.cache or "multi-prefix" not in user.cache["cap"]:
            return representation
        while representation[0] in self.ircd.prefix_symbols:
            representation = representation[1:]
        statusModes = listingUser.status(channel.name)
        return "{}{}".format("".join([self.ircd.prefixes[status][0] for status in statusModes]), representation)
    
    def whoStatus(self, cmd, data):
        if cmd != "WHO":
            return
        if not data["data"]: # some other module already suppressed this line; operating on it won't be super useful
            return
        user = data["user"]
        target = data["targetuser"]
        if data["channel"]:
            data["status"] = "".join([self.ircd.prefixes[status][0] for status in target.status(data["channel"].name)])

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.multi_prefix = None
    
    def spawn(self):
        self.multi_prefix = MultiPrefix().hook(self.ircd)
        if "cap" not in self.ircd.module_data_cache:
            self.ircd.module_data_cache["cap"] = {}
        self.ircd.module_data_cache["cap"]["multi-prefix"] = self.multi_prefix
        return {
            "actions": {
                "nameslistentry": [self.multi_prefix.namesListEntry],
                "commandextra": [self.multi_prefix.whoStatus]
            }
        }
    
    def cleanup(self):
        self.ircd.actions["nameslistentry"].remove(self.multi_prefix.namesListEntry)
        self.ircd.actions["commandextra"].remove(self.multi_prefix.whoStatus)
        del self.ircd.module_data_cache["cap"]["multi-prefix"]