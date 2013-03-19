from txircd.modbase import Mode

class PrivateMode(Mode):
	def listOutput(self, command, data):
		if command != "LIST":
			return data
		cdata = data["cdata"]
		if "p" in cdata["channel"].mode and cdata["channel"].name not in data["user"].channels:
			cdata["name"] = "*"
			cdata["topic"] = ""
	# other +p stuff is in other modules

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.mode_p = None
	
	def spawn(self):
		self.mode_p = PrivateMode()
		return {
			"modes": {
				"cnp": self.mode_p
			},
			"actions": {
				"commandextra": [self.mode_p.listOutput]
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cnp")
		self.ircd.actions["commandextra"].remove(self.mode_p.listOutput)