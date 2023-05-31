import aiohttp
import discord
from discord.ext import tasks
from discord.ui import Button, View
import asyncio
import json
import time
from random import randint
import keys
import os

crawlers = []

class MyClient(discord.Client):    
    async def on_ready(self):
        print(f"C'est parti ! ({self.user})")
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Vinted"))  
        #-----------------------------------#
        configs = json.loads(open("configs.json").read())
        
        session = aiohttp.ClientSession()
        session.headers["User-Agent"] = await pick_user()
        
        for i in range(len(configs['configs'])):
            if configs["configs"][i]["type"] == "free":
                crawlers.append(FreeVinted(i, session))
            else:
                crawlers.append(PremVinted(i, session))
            await crawlers[-1].ready()
            
            print(i, "lancé")
            
            await asyncio.sleep(7)

class FreeVinted:
    def __init__(self, order, session):
        configs = json.loads(open("configs.json").read())
        
        self.name = configs["configs"][order]["name"]
        self.url = join_url(configs["configs"][order])
        self.channel = client.get_channel(configs["configs"][order]["channel"])
        self.session = session
        
        self.last_ones = []
        
        self.history_path = f"histories/{self.name}.txt"
        self.h_count = 1
        
    async def ready(self):  
        self.h_count = await create_history(self.history_path, self.session, self.url)
        self.check.start()
        self.unload.start()
    
    @tasks.loop(minutes=3)
    async def check(self):  
        upd = await crawl(self.session, self.url)
        
        if upd["code"] != 0:
            await save_error("Code erroné", "upd", upd)
            return
        
        ids = map(lambda x: x["id"], upd["items"])
        nouveaux = await upd_history(self.history_path, ids)
    
        self.last_ones.extend(list(filter(lambda x: x["id"] in nouveaux, upd["items"])))
    
    @tasks.loop(seconds=3)
    async def unload(self):
        if len(self.last_ones) != 0:
            messages = []
            m_count = 2
            while m_count > 0 and len(self.last_ones) > 0:
                new = self.last_ones.pop(0)
                messages.append(send_annonce(new, self.channel, "Free"))
                m_count -= 1
            asyncio.gather(*messages)
            
            self.h_count += 2 - m_count
        
            if self.h_count > 1000:
                with open(self.history_path, "r") as file:
                    ids = file.readlines()
                with open(self.history_path, "w+") as file:
                    file.writelines(ids[600:])
                self.h_count = len(ids[600:])

class PremVinted:
    def __init__(self, order, session):
        configs = json.loads(open("configs.json").read())
        
        self.name = configs["configs"][order]["name"]
        self.url = join_url(configs["configs"][order])
        self.channel = client.get_channel(configs["configs"][order]["channel"])
        self.session = session
        
        self.history_path = f"histories/{self.name}.txt"
        self.h_count = 1
        
    async def ready(self):  
        self.h_count = await create_history(self.history_path, self.session, self.url)
        self.check.start()
    
    @tasks.loop(seconds=30)
    async def check(self):  
        upd = await crawl(self.session, self.url)
        
        if upd["code"] != 0:
            await save_error("Code erroné", "upd", upd)
            return
        
        ids = map(lambda x: x["id"], upd["items"])
        nouveaux = await upd_history(self.history_path, ids)
        
        if len(nouveaux) != 0:
            messages = []
            for new in filter(lambda x: x["id"] in nouveaux, upd["items"]):
                messages.append(send_annonce(new, self.channel, "Premium"))
            asyncio.gather(*messages)
        
        self.h_count += len(nouveaux)
        if self.h_count > 1000:
            with open(self.history_path, "r") as file:
                ids = file.readlines()
            with open(self.history_path, "w+") as file:
                file.writelines(ids[600:])
            self.h_count = len(ids[600:])

async def create_history(history_path, session, url):  
    h_count = 0
    if not os.path.exists(history_path):
        with open(history_path, "a+") as file:
            file.write("0")
    else:
        with open(history_path, "r") as file:
            h_count = len(file.readlines())
    
    upd = await crawl(session, url)
    ids = [upd["items"][x]["id"] for x in range(len(upd["items"]))]
    await upd_history(history_path, ids)
    
    return h_count

async def upd_history(history_path, ids):
    with open(history_path, "r+") as file:
        previous = file.read().split("\n")
        news = set(ids) - set(map(lambda x: int(x), previous))
        file.writelines(["\n" + str(n) for n in list(news)])
    return news

async def send_annonce(new, channel, categorie):
    e = discord.Embed(title=f"**{new['title']}**", description=f"", url=new['url'], colour=discord.Colour(00000))
    e.add_field(name="?? **Prix**", value=f"{new['price']}€")
    e.add_field(name="?? **Marque**", value=new['brand_title'])
    e.add_field(name="?? **Taille**", value=new['size_title'])
    e.add_field(name="???? **Vendeur**", value=f"[{new['user']['login']}]({new['user']['profile_url']})")
    photo = new['photo']
    if photo is not None:
        e.set_image(url=photo['url'])
    e.set_footer(text=f"{categorie}")
    
    details = Button(emoji="??", label="Détails", url=new['url'])
    acheter = Button(emoji="??", label="Acheter", url=f"https://www.vinted.fr/transaction/buy/new?source_screen=item&transaction%5Bitem_id%5D={new['id']}")
    
    view = View()
    view.add_item(details)
    view.add_item(acheter)
    
    await channel.send(embed=e, view=view)

async def crawl(s, url):
    async with s.get(url) as resp:
        try:
            data = await resp.json()
        except:
            await asyncio.sleep(.5)
            print("Website down (at least I think)", resp.text)
            data = await crawl(s, url)
        
        if data["code"] == 100:
            print("Uh oh, credentials needed...")
            await credentials(s)
            return await crawl(s, url)
        
        if data["code"] == 106:
            s.headers["User-Agent"] = await pick_user()
            return await crawl(s, url)
        
        return data

async def credentials(s):
    async with s.get("http://www.vinted.fr") as r:
        await r.text()
        if r.status != 200:
            await save_error(r.text, "-credentials-", r.status)

def join_url(params):
    exclude = ["type", "channel", "name"]
    url = "http://www.vinted.fr/api/v2/catalog/items?"
    for k, v in params.items():
        if k not in exclude:
            url += k + "=" + ",".join([str(_) for _ in v]) + "&"
    return url

async def save_error(e, cause, var):
    print(f"\nProblème avec {cause} à {time.strftime('%H:%M:%S')}\n")

async def pick_user():
    with open("user-agents.txt", "r") as f:
        uas = f.read().splitlines()
        return uas[randint(0, len(uas)-1)]


intents = discord.Intents.default()
intents.message_content = True

client = MyClient(intents=intents)
client.run(keys.discord_api)