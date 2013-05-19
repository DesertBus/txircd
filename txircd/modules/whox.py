from twisted.words.protocols import irc
from txircd.modbase import Module

irc.RPL_WHOSPCRPL = "354"

class WhoX(Module):
	def whox(self, cmd, data):
		if cmd != "WHO":
			return
		if data["phase"] != "display":
			return
		if not data["data"]: # Some other module already displayed this specially
			return
		fields = data["fields"]
		if not fields:
			return
		responses = []
		whoData = data["data"]
		if "c" in fields:
			responses.append(whoData["channel"])
		if "u" in fields:
			responses.append(whoData["ident"])
		if "i" in fields:
			if "o" in data["user"].mode:
				responses.append(whoData["ip"])
			else:
				responses.append("0.0.0.0")
		if "h" in fields:
			responses.append(whoData["host"])
		if "s" in fields:
			responses.append(whoData["server"])
		if "n" in fields:
			responses.append(whoData["nick"])
		if "f" in fields:
			responses.append("{}{}{}".format("G" if whoData["away"] else "H", "*" if whoData["oper"] else "", whoData["status"]))
		if "d" in fields:
			responses.append(str(whoData["hopcount"]))
		if "l" in fields:
			responses.append(str(whoData["idle"]))
		if "a" in fields:
			responses.append(whoData["account"])
		if "r" in fields:
			responses.append(":{}".format(whoData["gecos"]))
		data["data"] = {}
		data["user"].sendMessage(irc.RPL_WHOSPCRPL, *responses)

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.whox = None
	
	def spawn(self):
		self.whox = WhoX().hook(self.ircd)
		return {
			"actions": {
				"commandextra": [self.whox.whox]
			}
		}
	
	def cleanup(self):
		self.ircd.actions["commandextra"].remove(self.whox.whox)