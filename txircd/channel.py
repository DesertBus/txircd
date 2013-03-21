from txircd.utils import now

class IRCChannel(object):
	def __init__(self, ircd, name):
		self.ircd = ircd
		self.name = name
		self.created = now()
		self.topic = ""
		self.topicSetter = ""
		self.topicTime = now()
		self.mode = {}
		self.users = set()
		self.metadata = { # split into metadata key namespaces, see http://ircv3.atheme.org/specification/metadata-3.2
			"server": {},
			"user": {},
			"client": {},
			"ext": {},
			"private": {}
		}
		self.cache = {}
	
	def modeString(self, user):
		modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
		params = []
		for mode, param in self.mode.iteritems():
			modetype = self.ircd.channel_mode_type[mode]
			if modetype > 0:
				modes.append(mode)
				if param:
					params.append(self.ircd.channel_modes[modetype][mode].showParam(user, self, param))
		return ("+{} {}".format("".join(modes), " ".join(params)) if params else "+{}".format("".join(modes)))
	
	def setTopic(self, topic, setter):
		self.topic = topic
		self.topicSetter = setter
		self.topicTime = now()
	
	def setMetadata(self, namespace, key, value):
		oldValue = self.metadata[namespace][key] if key in self.metadata[namespace] else ""
		self.metadata[namespace][key] = value
		for modfunc in self.ircd.actions["metadataupdate"]:
			modfunc(self, namespace, key, oldValue, value)
	
	def delMetadata(self, namespace, key):
		for modfunc in self.ircd.actions["metadataupdate"]:
			modfunc(self, namespace, key, self.metadata[namespace][key], "")
		del self.metadata[namespace][key]