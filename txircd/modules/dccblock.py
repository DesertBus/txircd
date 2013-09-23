from txircd.modbase import Module

class DCCBlock(Module):
    def blockDCC(self, user, command, data):
        if command != "PRIVMSG":
            return data
        if "message" not in data or not data["message"]:
            return data
        words = data["message"].split(" ")
        if words[0] == "\x01DCC":
            user.sendMessage("NOTICE", ":DCC is not allowed on this server.")
            return {}
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.dcc_block = None
    
    def spawn(self):
        self.dcc_block = DCCBlock()
        return {
            "actions": {
                "commandpermission": self.dcc_block.blockDCC
            }
        }