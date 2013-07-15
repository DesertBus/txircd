from twisted.internet.abstract import isIPv6Address
from txircd.modbase import Mode
from Crypto.Hash import SHA256

class CloakingMode(Mode):
    def checkSet(self, user, target, param):
        target.setHostname(self.applyCloak(target.ip))
        return [True, param]
    
    def checkUnset(self, user, target, param):
        target.setHostname(target.realhost)
        return [True, param]
    
    def applyCloak(self, ip):
        if isIPv6Address(ip):
            return self.applyCloak6(ip)
        else:
            return self.applyCloak4(ip)
    
    def applyCloak6(self, ip):
        if "::" in ip:
            # Our cloaking method relies on a fully expanded address
            count = 6 - ip.replace("::", "").count(":")
            ip = ip.replace("::", ":{}:".format(":".join(["0000" for i in range(count)])))
            if ip[0] == ":":
                ip = "0000{}".format(ip)
            if ip[-1] == ":":
                ip = "{}0000".format(ip)
        pieces = ip.split(":")
        for index, piece in enumerate(pieces):
            pieceLen = len(piece)
            if pieceLen < 4:
                pieces[index] = "{}{}".format("".join(["0" for i in range(4 - pieceLen)]), piece)
        hashedParts = []
        pieces.reverse()
        for i in range(len(pieces)):
            piecesGroup = pieces[i:]
            piecesGroup.reverse()
            wholePiece = "".join(piecesGroup)
            pieceHash = SHA256.new(wholePiece)
            hashedParts.append(pieceHash.hexdigest()[:5])
        return ".".join(hashedParts)
    
    def applyCloak4(self, ip):
        pieces = ip.split(".")
        pieces.reverse()
        hashedParts = []
        for i in range(len(pieces)):
            piecesGroup = pieces[i:]
            piecesGroup.reverse()
            wholePiece = "".join(piecesGroup)
            pieceHash = SHA256.new(wholePiece)
            hashedParts.append(pieceHash.hexdigest()[:8])
        return ".".join(hashedParts)

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "unx": CloakingMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("unx")