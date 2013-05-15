from txircd.modbase import Module
from base64 import b64decode

class SaslPlainMechanism(Module):
	def authenticate(self, user, authentication):
		try:
			authenticationID, authorizationID, password = b64decode(authentication[0]).split("\0")
		except TypeError:
			user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
			return False
		except ValueError:
			user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
			return False
		if "server_sasl_agent" not in self.ircd.servconfig or self.ircd.servconfig["server_sasl_agent"] == "":
			if "sasl_agent" not in self.ircd.module_data_cache:
				user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
				return False
			return self.ircd.module_data_cache["sasl_agent"].authenticate(user, authenticationid=authenticationID, authorizationid=authorizationID, password=password)
		# TODO: The rest of this doesn't really make sense until s2s, but we'll return false for now since it's failing
		return False
	
	def bindSaslResult(self, user, successFunction, failureFunction):
		if "server_sasl_agent" not in self.ircd.servconfig or self.ircd.servconfig["server_sasl_agent"] == "":
			if "sasl_agent" not in self.ircd.module_data_cache:
				user.sendMessage(irc.ERR_SASLFAILED, ":SASL authentication failed")
				return
			self.ircd.module_data_cache["sasl_agent"].bindSaslResult(user, successFunction, failureFunction)
		# TODO: server_sasl_agent stuff when s2s

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		if "sasl_mechanisms" not in self.ircd.module_data_cache:
			self.ircd.module_data_cache["sasl_mechanisms"] = {}
		self.ircd.module_data_cache["sasl_mechanisms"]["PLAIN"] = SaslPlainMechanism().hook(self.ircd)
		return {}
	
	def cleanup(self):
		del self.ircd.module_data_cache["sasl_mechanisms"]["PLAIN"]