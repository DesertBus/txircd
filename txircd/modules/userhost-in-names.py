from txircd.modbase import Module

class UserhostInNames(Module):
	def namesListEntry(self, user, channel, listingUser, representation):
		return "{}!{}@{}".format(representation, listingUser.username, listingUser.hostname)
	
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

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.userhost_in_names = None
	
	def spawn(self):
		self.userhost_in_names = UserhostInNames().hook(self.ircd)
		if "cap" not in self.ircd.module_data_cache:
			self.ircd.module_data_cache["cap"] = {}
		self.ircd.module_data_cache["cap"]["userhost-in-names"] = self.userhost_in_names
		return {
			"actions": {
				"nameslistentry": [self.userhost_in_names.namesListEntry]
			}
		}
	
	def cleanup(self):
		self.ircd.actions["nameslistentry"].remove(self.userhost_in_names.namesListEntry)
		del self.ircd.module_data_cache["cap"]["userhost-in-names"]