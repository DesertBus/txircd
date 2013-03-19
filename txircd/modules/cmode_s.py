from txircd.modbase import Mode

class SecretMode(Mode):
	def listOutput(self, command, data):
		if command != "LIST":
			return data
		cdata = data["cdata"]
		if "s" in cdata["channel"].mode and cdata["channel"].name not in data["user"].channels:
			data["cdata"].clear()
	# other +s stuff is hiding in other modules.

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.mode_s = None
	
	def spawn(self):
		self.mode_s = SecretMode()
		return {
			"modes": {
				"cns": self.mode_s
			},
			"actions": {
				"commandextra": [self.mode_s.listOutput]
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cns")
		self.ircd.actions["commandextra"].remove(self.mode_s.listOutput)