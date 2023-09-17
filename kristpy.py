import asyncio
import os.path
import aiohttp
import json
import certifi
import ssl
import hashlib as hl
class utils:
    @classmethod
    def sha256(cls,inputstr:str):
        return hl.sha256(inputstr.encode("iso-8859-1")).hexdigest()
    @classmethod
    def makeaddressbyte(cls,byte:int):
        byte = 48 + (byte//7)
        val = 101 if byte + 39 > 122 else (byte + 39 if byte > 57 else byte)
        val =val.to_bytes(1,"little")
        return val.decode("iso-8859-1")

    @classmethod
    def makeV2Address(cls,key:str,prefix="k"):
        protein = []
        stick = utils.sha256(utils.sha256(key))
        n = 0

        addr = prefix
        while n !=9:
            if n < 9:
                protein.append(stick[:2])
                stick = utils.sha256(utils.sha256(stick))
            n+= 1
        n = 0
        while n < 9:
            link = int(stick[(2*n):2+(2*n)],16) % 9
            if len(protein[link]) != 0:
                addr += utils.makeaddressbyte(int(protein[link], 16))
                protein[link] = ""
                n += 1
            else:
                stick = utils.sha256(stick)

        return addr

# if __name__ == "__main__":
# raise Exception("This file is a module, and must be imported")
class Event:  # Dummy base Class to define events, has no parameters!
    pass


class transactionIDHandler:
    def __init__(self):
        self.id = 0

    def getID(self):
        self.id += 1
        return self.id


class newTransactionEvent(Event):
    def __init__(self, toAddr: str, amount: int, meta: str = None):
        self.toAddr = toAddr
        self.amount = amount
        self.meta = meta
    def generateTransactionString(self, id_manager: transactionIDHandler):
        tx_id = id_manager.getID()
        if self.meta:
            TxStr = f'{{"id":{tx_id},"type":"make_transaction","to":"{self.toAddr}","amount":{self.amount},"metadata":"{self.meta}"}}'
        else:
            TxStr = f'{{"id":{tx_id},"type":"make_transaction","to":"{self.toAddr}","amount":{self.amount}}}'
        return TxStr


class recievedTransactionEvent(Event):
    def __init__(self, fromAddr: str, toAddr: str, amount: int, meta: str = None, name:str = None):
        self.fromAddr = fromAddr
        self.toAddr = toAddr
        self.amount = amount
        self.meta = meta
        self.meta = meta
        self.name = name




class eventStack:
    def __init__(self):
        self.events = []

    def queue_event(self, event: Event):
        assert isinstance(event, Event)
        self.events.append(event)

    async def listen(self):
        while True:
            if self.events:
                yield self.events[0]
                self.events.pop(0)
            else:
                await asyncio.sleep(1)
def parseCommonMeta(meta:str):
    mta = meta.split(";")
    mta2 = []
    for s in mta:
        mta_segment = s.split("=", 1)
        if len(mta_segment) == 1:
            mta_segment.append("__KRISTPY_DEFAULT_VALUE")
        mta2.append(mta_segment)
    return dict(mta2)

class wallet:
    """A Krist Wallet with Websocket Handling contained"""

    def __init__(self):
        self.pkey = None
        self.id_manager = transactionIDHandler()
        self.ws_transactions = eventStack()
        self.address = ""
        self.events = eventStack()
        self.session = None

    @classmethod
    async def create(cls, pkey):
        self = wallet()
        self.pkey = pkey

        self.address = utils.makeV2Address(pkey)
        asyncio.create_task(self.websocketHandler())
        return self

    async def refund(self,tx:recievedTransactionEvent,amount=-1,newmeta=None):
        meta = parseCommonMeta(tx.meta)
        if "return" in meta and meta["return"] != "__KRISTPY_DEFAULT_VALUE":
            tx.fromAddr = meta["return"]
        if amount == -1 or amount > tx.amount:
            amount = tx.amount
        if not newmeta:
            newmeta = "You have been refunded for this transaction"
        await self.make_transaction(tx.fromAddr,amount,newmeta)


    async def make_transaction(self, toAddr: str, amount: int, meta: str = None):
        self.events.queue_event(newTransactionEvent(toAddr, amount, meta))

    async def send_messages(self, ws):
        async for event in self.events.listen():
            await ws.send_str(event.generateTransactionString(self.id_manager))

    async def websocketHandler(self):
        tmp_e = {'privatekey': self.pkey}
        ctx_inst = ssl.SSLContext()
        ctx_inst.verify_mode = ssl.CERT_REQUIRED
        ctx_inst.load_verify_locations(cafile=os.path.abspath(certifi.where()), capath=None, cadata=None)
        async with aiohttp.ClientSession() as cs:
            async with cs.post("https://krist.dev/ws/start", data=json.dumps(tmp_e),
                                         headers={'content-type': 'application/json'}) as resp:

                rdata = await resp.json()

            async with cs.ws_connect(rdata["url"], ssl=ctx_inst) as socket:
                await socket.send_str(
                    '{\"id\":' + str(self.id_manager.getID()) + ',\"type\":\"subscribe\",\"event\":\"ownTransactions\"}')
                asyncio.create_task(self.send_messages(socket))
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        json_data = message.data
                        decoder = json.JSONDecoder()
                        data = decoder.decode(json_data)
                        if data["type"] == "event" and data["event"] == "transaction":
                            transaction = data["transaction"]

                            if transaction["type"] == "transfer":
                                self.ws_transactions.queue_event(
                                    recievedTransactionEvent(transaction["from"], transaction["to"], transaction["value"], transaction["metadata"], transaction["sent_name"]))
