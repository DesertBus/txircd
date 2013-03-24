from txircd.modbase import Mode

class OperMode(Mode):
	def checkSet(self, target, param):
		return False # Should only be set by the OPER command; hence, reject any normal setting of the mode
	
	def checkWhoFilter(self, cmd, data):
		if cmd != "WHO":
			return
		if "o" in data["data"]["cmdfilters"] and not data["data"]["oper"]:
			data["data"] = {}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.oper_mode = None
	
	def spawn(self):
		self.oper_mode = OperMode()
		return {
			"modes": {
				"uno": self.oper_mode
			},
			"actions": {
				"commandextra": [self.oper_mode.checkWhoFilter]
		}
	
	def cleanup(self):
		self.ircd.removeMode("uno")
		self.ircd.actions["commandextra"].remove(self.oper_mode.checkWhoFilter)