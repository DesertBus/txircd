from twisted.words.protocols import irc
from txircd.modbase import Command

irc.ERR_INVALIDCAPCMD = "410" # as defined in http://ircv3.atheme.org/specification/capability-negotiation-3.1

class CapCommand(Command):
	def onUse(self, user, data):
		subcmd = data["subcmd"]
		if user.registered > 0 and "cap_negotiating" not in user.cache:
			user.cache["cap_negotiating"] = True
			user.registered += 1 # On receipt of a CAP command, block registration until CAP END is received
		if subcmd == "LS":
			user.sendMessage("CAP", "LS", ":{}".format(" ".join(self.ircd.module_data_cache["cap"].keys())))
		elif subcmd == "LIST":
			if "cap" not in user.cache:
				user.sendMessage("CAP", "LIST", ":")
			else:
				user.sendMessage("CAP", "LIST", ":{}".format(" ".join(user.cache["cap"])))
		elif subcmd == "REQ":
			ack = []
			nak = []
			for capability in data["list"]:
				if capability[0] == "-":
					capabilityName = capability[1:]
					if capabilityName in self.ircd.module_data_cache["cap"] and self.ircd.module_data_cache["cap"][capabilityName].capRequestRemove(user, capability):
						if "cap" in user.cache and capabilityName in user.cache["cap"]:
							user.cache["cap"].remove(capabilityName)
						ack.append(capability) # send acknowledgement of capability removal if capability is already not set
					else:
						nak.append(capability)
				elif capability in self.ircd.module_data_cache["cap"]:
					if self.ircd.module_data_cache["cap"][capability].capRequest(user, capability):
						if "cap" in user.cache:
							user.cache["cap"].append(capability)
						else:
							user.cache["cap"] = [capability]
						ack.append(capability)
					else:
						nak.append(capability)
				else:
					nak.append(capability)
			if ack:
				user.sendMessage("CAP", "ACK", ":{}".format(" ".join(ack)))
			if nak:
				user.sendMessage("CAP", "NAK", ":{}".format(" ".join(nak)))
		elif subcmd == "ACK":
			ack = []
			nak = []
			for capability in data["list"]:
				if capability[0] == "-":
					capabilityName = capability[1:]
					if capabilityName in self.ircd.module_data_cache["cap"] and self.ircd.module_data_cache["cap"][capabilityName].capAcknowledgeRemove(user, capability):
						if "cap" in user.cache and capabilityName in user.cache["cap"]:
							user.cache["cap"].remove(capabilityName)
						ack.append(capability)
					else:
						nak.append(capability)
				elif capability in self.ircd.module_data_cache["cap"]:
					if self.ircd.module_data_cache["cap"][capability].capAcknowledge(user, capability):
						if "cap" in user.cache:
							user.cache["cap"].append(capability)
						else:
							user.cache["cap"] = [capability]
						ack.append(capability)
					else:
						nak.append(capability)
				else:
					nak.append(capability)
			if ack:
				user.sendMessage("CAP", "ACK", ":{}".format(" ".join(ack)))
			if nak:
				user.sendMessage("CAP", "NAK", ":{}".format(" ".join(nak)))
		elif subcmd == "CLEAR":
			if "cap" not in user.cache:
				user.sendMessage("CAP", "ACK", ":")
			else:
				removing = []
				for capability in user.cache["cap"]:
					if self.ircd.module_data_cache["cap"][capability].capClear(user, capability):
						removing.append(capability)
				for capability in removing:
					user.cache["cap"].remove(capability)
				user.sendMessage("CAP", "ACK", ":{}".format(" ".join(["-{}".format(capability) for capability in removing])))
		elif subcmd == "END":
			if "cap_negotiating" in user.cache:
				del user.cache["cap_negotiating"]
				user.registered -= 1
				if user.registered == 0:
					user.register()
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "CAP", ":Not enough parameters")
			return {}
		subcmd = params[0].upper()
		caplist = params[1] if len(params) > 1 else []
		if subcmd not in ["LS", "LIST", "REQ", "ACK", "CLEAR", "END"]:
			user.sendMessage(irc.ERR_INVALIDCAPCMD, ":Invalid CAP subcommand")
			return {}
		return {
			"subcmd": subcmd,
			"list": caplist.split(" ")
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		if "cap" not in self.ircd.module_data_cache:
			self.ircd.module_data_cache["cap"] = {}
		return {
			"commands": {
				"CAP": CapCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["CAP"]