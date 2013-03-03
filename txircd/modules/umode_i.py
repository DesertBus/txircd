from txircd.modbase import Mode

class InvisibleMode(Mode):
	def namesListEntry(self, recipient, channel, user, representation):
		if channel not in recipient.channels and "i" in user.mode:
			return ""
		return representation

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"uni": InvisibleMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("uni")